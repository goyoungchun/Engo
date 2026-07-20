"""Entry point: application object, tray icon, single-instance guard.

The tray icon is the process owner, not the main window. That is what lets the
main window be *destroyed* when the user closes it: measured on 3,000 rows,
closing frees all of its widgets and their models, leaving only the tray icon
and whatever sticky notes are open. (Windows keeps the freed pages in the
process working set, so Task Manager may not drop by the same amount -- the
heap is released and reused, which is what matters for a program that sits in
the tray all day.)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

if __package__ in (None, ""):                      # allow `python app/main.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "app"

from . import db, i18n, theme, tts                       # noqa: E402
from .i18n import t                                 # noqa: E402
from .ui.common import round_menu                   # noqa: E402
from .ui.main_window import MainWindow              # noqa: E402
from .ui.sticky import StickyManager                # noqa: E402
from .ui import voice_setup                         # noqa: E402

APP_ID = "Engo.local.singleinstance"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Engo"


# --------------------------------------------------------------------------
# icon (drawn in code so the app ships without binary assets)
# --------------------------------------------------------------------------

def app_icon(p: theme.Palette) -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(p.primary))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(1, 1, size - 2, size - 2, size * 0.26, size * 0.26)
        font = QFont(theme.ENGLISH_FONT)
        font.setPointSizeF(size * 0.52)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(p.primary_text))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "E")
        painter.end()
        icon.addPixmap(pixmap)
    return icon


# --------------------------------------------------------------------------
# autostart (Windows Run key)
# --------------------------------------------------------------------------

def _launch_command() -> str:
    # --tray: on login the app comes up as a tray icon plus the notes that
    # were open, without stealing focus with the main window.
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    # pythonw.exe so the console window does not flash on login
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    runner = quiet if quiet.exists() else exe
    script = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{runner}" "{script}" --tray'


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(value)
    except (ImportError, OSError):
        return False


def set_autostart(enabled: bool) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except (ImportError, OSError):
        return False


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------

class EngoApp:
    def __init__(self, app: QApplication, palette: theme.Palette):
        self.app = app
        self.palette = palette
        self.window: MainWindow | None = None
        self.sticky = StickyManager(palette)

        self.tray = QSystemTrayIcon(app_icon(palette), app)
        self.tray.setToolTip("Engo")
        self._build_tray_menu()
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        restored = self.sticky.restore()
        if restored:
            self.tray.showMessage("Engo", t("notes_restored", n=restored),
                                  app_icon(palette), 3000)

    # -- tray ------------------------------------------------------------
    def _build_tray_menu(self) -> None:
        menu = round_menu(QMenu())
        self.tray_menu = menu

        self.act_open = menu.addAction("", self.show_window)
        menu.addSeparator()
        self.act_note_today = menu.addAction(
            "", lambda: self.open_sticky("expressions", "today"))
        self.act_note_weak = menu.addAction(
            "", lambda: self.open_sticky("expressions", "weak"))
        self.act_note_sent = menu.addAction(
            "", lambda: self.open_sticky("sentences", ""))
        menu.addSeparator()
        self.act_refresh = menu.addAction("", self.sticky.refresh_all)
        self.act_close_notes = menu.addAction(
            "", lambda: self.sticky.close_all(remember=False))
        menu.addSeparator()

        self.theme_menu = round_menu(menu.addMenu(""))
        self.theme_actions = {}
        for key, p in theme.PALETTES.items():
            action = QAction(self.theme_menu, checkable=True)
            action.setChecked(key == self.palette.key)
            action.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            self.theme_menu.addAction(action)
            self.theme_actions[key] = action

        self.lang_menu = round_menu(menu.addMenu(""))
        self.lang_actions = {}
        for code, label in i18n.LANGUAGES.items():
            action = QAction(label, self.lang_menu, checkable=True)
            action.setChecked(code == i18n.language())
            action.triggered.connect(lambda _=False, c=code: self.set_language(c))
            self.lang_menu.addAction(action)
            self.lang_actions[code] = action
        menu.addSeparator()

        self.autostart_action = QAction(menu, checkable=True)
        self.autostart_action.setChecked(autostart_enabled())
        self.autostart_action.triggered.connect(self._toggle_autostart)
        menu.addAction(self.autostart_action)
        menu.addSeparator()

        self.act_quit = menu.addAction("", self.quit)
        self.tray.setContextMenu(menu)
        self._retranslate_tray()

    def _retranslate_tray(self) -> None:
        self.act_open.setText(t("tray_open"))
        self.act_note_today.setText(t("sticky_new"))
        self.act_note_weak.setText(t("sticky_weak"))
        self.act_note_sent.setText(t("sticky_sentences"))
        self.act_refresh.setText(t("tray_refresh_notes"))
        self.act_close_notes.setText(t("tray_close_notes"))
        self.theme_menu.setTitle(t("menu_theme"))
        for key, action in self.theme_actions.items():
            p = theme.PALETTES[key]
            action.setText(p.name_en if i18n.language() == "en" else p.name_ko)
        self.lang_menu.setTitle(t("menu_language"))
        self.autostart_action.setText(t("tray_autostart"))
        self.act_quit.setText(t("tray_quit"))

    def _on_tray_activated(self, reason) -> None:
        # Left click opens the window. It used to spawn a note, which meant an
        # absent-minded click left a pile of notes on screen.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()
        elif reason == QSystemTrayIcon.MiddleClick:
            self.open_sticky("expressions", "today")

    def _toggle_autostart(self, checked: bool) -> None:
        if not set_autostart(checked):
            self.autostart_action.setChecked(autostart_enabled())
            QMessageBox.warning(None, t("autostart_failed"),
                                t("autostart_failed_body"))

    # -- theme / language --------------------------------------------------
    def set_theme(self, key: str) -> None:
        if key == self.palette.key:
            return
        self.palette = theme.apply(self.app, key)
        db.set_meta("theme", key)
        icon = app_icon(self.palette)
        self.app.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.sticky.restyle(self.palette)
        if self.window is not None:
            # The window keeps its own icon copy, so setting it on the
            # application alone left the old colour in the title bar and
            # taskbar until the next restart.
            self.window.setWindowIcon(icon)
            self.window.restyle(self.palette)
        for k, action in self.theme_actions.items():
            action.setChecked(k == key)

    def set_language(self, code: str) -> None:
        if code == i18n.language():
            return
        i18n.set_language(code)
        i18n.install_qt_translator(self.app)
        db.set_meta("language", code)
        self._retranslate_tray()
        for c, action in self.lang_actions.items():
            action.setChecked(c == code)
        # Notes bake their text in at build time, so they are recreated.
        self.sticky.rebuild()
        if self.window is not None:
            self.window.retranslate()

    # -- windows ---------------------------------------------------------
    def show_window(self) -> None:
        if self.window is None:
            self.window = MainWindow(self.palette, lambda: self.sticky.count)
            self.window.setWindowIcon(app_icon(self.palette))
            self.window.stickyRequested.connect(self._on_sticky_requested)
            self.window.themeChanged.connect(self.set_theme)
            self.window.languageChanged.connect(self.set_language)
            self.window.closedToTray.connect(self._on_window_closed)
            self.window.quitRequested.connect(self.quit)
        self.window.show()
        self.window.setWindowState(
            self.window.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.window.raise_()
        self.window.activateWindow()

    def _on_window_closed(self) -> None:
        """Tear the window down so it stops holding memory while in the tray."""
        # The speech engine's status callback points at this window; left in
        # place it would fire RuntimeErrors at a destroyed object every time a
        # sticky note speaks, and keep the dead window's wrapper alive.
        tts.set_status_listener(None)
        window = self.window
        self.window = None
        if window is not None:
            window.deleteLater()
        self.sticky.refresh_all()

    def _on_sticky_requested(self, kind: str, tag: str) -> None:
        if kind == "weak":
            self.open_sticky("expressions", "weak")
        else:
            self.open_sticky(kind, "" if tag else "today", tag)

    def open_sticky(self, kind: str, query: str, tag: str = "") -> None:
        self.sticky.open_new(kind=kind, query=query or "today", tag=tag)
        if self.window is not None:
            self.window.refresh_status()

    # -- lifecycle -------------------------------------------------------
    def on_voices_ready(self, ok: bool) -> None:
        """Rebuild the window so the 🔊 buttons appear without a restart."""
        if not ok or self.window is None:
            return
        self.window.prepare_quit()
        self.window.close()
        self.window.deleteLater()
        self.window = None
        self.show_window()

    def handle_second_instance(self) -> None:
        self.show_window()

    def quit(self) -> None:
        if self.window is not None:
            self.window.prepare_quit()
            self.window.close()
        self.sticky.close_all(remember=True)
        tts.shutdown()
        self.tray.hide()
        db.close()
        self.app.quit()


def _install_excepthook() -> None:
    """Log unexpected errors and say something, instead of dying silently.

    Under pythonw there is no console: an uncaught exception in a slot prints
    a traceback nobody can see and the action just doesn't happen. Writing to
    a log file gives failures a paper trail, and the dialog tells the user
    the action failed rather than leaving them to wonder.
    """
    import traceback

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log = db.default_data_dir() / "error.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                import datetime
                fh.write(f"\n--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
                fh.write(text)
        except OSError:
            pass
        try:
            QMessageBox.critical(None, "Engo",
                                 t("unexpected_error", path=str(log)))
        except Exception:
            pass          # a broken hook must never recurse

    sys.excepthook = hook


def main() -> int:
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Engo")
    app.setOrganizationName("Engo")
    app.setQuitOnLastWindowClosed(False)   # the tray owns the process lifetime

    # Single instance: a second launch just raises the first one's window.
    socket = QLocalSocket()
    socket.connectToServer(APP_ID)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(APP_ID)
    server = QLocalServer()
    server.listen(APP_ID)

    # Preferences live in the database, so it has to be open before the first
    # pixel is drawn.
    db.connect()
    _install_excepthook()
    i18n.set_language(db.get_meta("language", i18n.DEFAULT))
    i18n.install_qt_translator(app)
    palette = theme.apply(app, db.get_meta("theme", theme.DEFAULT_PALETTE))
    app.setWindowIcon(app_icon(palette))

    studio = EngoApp(app, palette)
    server.newConnection.connect(
        lambda: (server.nextPendingConnection(), studio.handle_second_instance())
    )

    # First run: the speech models are not in the repository, so offer to
    # fetch them. Skipped when starting minimised at login -- a download
    # prompt nobody is looking at helps no one.
    if "--tray" not in sys.argv and voice_setup.should_offer():
        QTimer.singleShot(400, lambda: studio.on_voices_ready(
            voice_setup.offer(studio.window)))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        studio.show_window()
    elif "--tray" in sys.argv:
        # Started by autostart: come up quietly with just the notes.
        if not studio.sticky.count:
            QTimer.singleShot(0, lambda: studio.open_sticky("expressions", "today"))
    else:
        studio.show_window()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())












