"""Main window: five feature tabs, built lazily, plus theme and language menus."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import db, i18n, repo, theme, tts
from ..i18n import t
from . import effects
from .common import round_corners, round_menu
from .entry_tab import EntryTab
from .reading_tab import ReadingTab
from .sync_tab import SyncTab

TAB_KEYS = ["tab_expressions", "tab_reading", "tab_sentences",
            "tab_grammar", "tab_data"]


class MainWindow(QMainWindow):
    stickyRequested = Signal(str, str)   # kind, tag
    themeChanged = Signal(str)
    languageChanged = Signal(str)
    closedToTray = Signal()

    def __init__(self, palette: theme.Palette, sticky_count):
        super().__init__()
        self.palette = palette
        self._sticky_count = sticky_count
        self._built: dict[int, QWidget] = {}
        self._quitting = False

        self.resize(1180, 720)
        self.setMinimumSize(QSize(900, 560))

        self._build_tabs()
        self._build_menu()

        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label)

        self.retranslate()
        # Only the first tab is constructed up front; the rest cost nothing
        # until the user actually opens them.
        self._ensure_tab(0)

    # -- construction ----------------------------------------------------
    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tab_bar = effects.SlidingTabBar(self.palette)
        self.tabs.setTabBar(self.tab_bar)
        # Must be connected before the lazy-build slot, so the outgoing page is
        # photographed while it is still the current one.
        self.tab_bar.tabBarClicked.connect(lambda _: self.slider.snapshot())
        # Each tab starts as an empty host with a layout. The real widget is
        # dropped into that layout on first visit, so the tab itself is never
        # removed and re-inserted -- doing that shifted the current index and
        # lost the tab's label.
        self._hosts: list[QVBoxLayout] = []
        for _ in TAB_KEYS:
            host = QWidget()
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            self._hosts.append(layout)
            self.tabs.addTab(host, "")
        self.tabs.currentChanged.connect(self._ensure_tab)
        self.slider = effects.PageSlider(self.tabs, self)
        self.setCentralWidget(self.tabs)

    def _factory(self, index: int) -> QWidget:
        if index == 0:
            tab = EntryTab("expressions", self.palette)
        elif index == 1:
            tab = ReadingTab(self.palette)
            tab.sendToSentences.connect(self._add_sentence)
        elif index == 2:
            tab = EntryTab("sentences", self.palette)
        elif index == 3:
            tab = EntryTab("grammar", self.palette)
        else:
            tab = SyncTab(self.palette)
        tab.dataChanged.connect(self.refresh_status)
        return tab

    def _ensure_tab(self, index: int) -> None:
        self._dismiss_stray_windows()
        if index in self._built or not 0 <= index < len(self._hosts):
            return
        widget = self._factory(index)
        self._built[index] = widget
        self._hosts[index].addWidget(widget)
        effects.install(widget)

    def _dismiss_stray_windows(self) -> None:
        """Close anything a tab left floating before moving to another one.

        Nothing should normally be open here -- modal dialogs block the tab
        switch, so they cannot survive it. This exists as a backstop: a widget
        that is made visible before it is put in a layout briefly becomes a
        top-level window of its own, and one of those escaping unnoticed is
        exactly the kind of thing that accumulates.
        """
        from PySide6.QtWidgets import QApplication, QDialog

        for tab in self._built.values():
            for dialog in tab.findChildren(QDialog):
                if dialog.isVisible():
                    dialog.close()
        for widget in QApplication.topLevelWidgets():
            if widget is self or not widget.isVisible():
                continue
            # A visible top-level widget that is neither a window we own nor a
            # real dialog is an accident; a stray button or label cannot be
            # anything the user meant to see.
            if widget.__class__.__name__ in ("QPushButton", "QLabel", "QFrame"):
                widget.hide()
                widget.deleteLater()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        self._menus = []

        def add_menu(parent, title=""):
            menu = parent.addMenu(title)
            round_menu(menu)
            self._menus.append(menu)
            return menu

        self.study_menu = add_menu(bar)
        self.act_note = QAction(self)
        self.act_note.setShortcut(QKeySequence("Ctrl+N"))
        self.act_note.triggered.connect(
            lambda: self.stickyRequested.emit("expressions", ""))
        self.study_menu.addAction(self.act_note)

        self.act_weak = QAction(self)
        self.act_weak.triggered.connect(lambda: self.stickyRequested.emit("weak", ""))
        self.study_menu.addAction(self.act_weak)

        self.act_sent_note = QAction(self)
        self.act_sent_note.triggered.connect(
            lambda: self.stickyRequested.emit("sentences", ""))
        self.study_menu.addAction(self.act_sent_note)
        self.study_menu.addSeparator()

        self.act_save = QAction(self)
        self.act_save.setShortcut(QKeySequence.Save)
        self.act_save.triggered.connect(self._save_current_tab)
        self.study_menu.addAction(self.act_save)
        self.study_menu.addSeparator()

        self.act_speak = QAction(self)
        self.act_speak.setShortcut(QKeySequence("Ctrl+P"))
        self.act_speak.triggered.connect(self._speak_current_tab)
        self.act_speak.setEnabled(tts.installed())
        self.study_menu.addAction(self.act_speak)
        self.study_menu.addSeparator()

        self.act_hide = QAction(self)
        self.act_hide.setShortcut(QKeySequence("Ctrl+W"))
        self.act_hide.triggered.connect(self.close)
        self.study_menu.addAction(self.act_hide)

        # -- view: theme colour + language --------------------------------
        self.view_menu = add_menu(bar)
        self.theme_menu = add_menu(self.view_menu)
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for key, palette in theme.PALETTES.items():
            action = QAction(self, checkable=True)
            action.setChecked(key == self.palette.key)
            action.triggered.connect(lambda _=False, k=key: self.themeChanged.emit(k))
            theme_group.addAction(action)
            self.theme_menu.addAction(action)
            self.theme_actions[key] = action

        # -- voice --------------------------------------------------------
        self.voice_menu = add_menu(self.view_menu)
        self.voice_menu.setEnabled(tts.installed())
        voice_group = QActionGroup(self)
        voice_group.setExclusive(True)
        self.voice_actions: dict[str, QAction] = {}
        current_voice = "off" if not tts.enabled() else tts.gender()
        for key in ("female", "male", "off"):
            action = QAction(self, checkable=True)
            action.setChecked(key == current_voice)
            action.triggered.connect(lambda _=False, k=key: self._set_voice(k))
            voice_group.addAction(action)
            self.voice_menu.addAction(action)
            self.voice_actions[key] = action

        self.lang_menu = add_menu(self.view_menu)
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        self.lang_actions: dict[str, QAction] = {}
        for code, label in i18n.LANGUAGES.items():
            action = QAction(label, self, checkable=True)
            action.setChecked(code == i18n.language())
            action.triggered.connect(lambda _=False, c=code: self.languageChanged.emit(c))
            lang_group.addAction(action)
            self.lang_menu.addAction(action)
            self.lang_actions[code] = action

        self.data_menu = add_menu(bar)
        self.act_open_data = QAction(self)
        self.act_open_data.triggered.connect(lambda: self.tabs.setCurrentIndex(4))
        self.data_menu.addAction(self.act_open_data)
        self.act_open_folder = QAction(self)
        self.act_open_folder.triggered.connect(self._open_data_folder)
        self.data_menu.addAction(self.act_open_folder)

        self.help_menu = add_menu(bar)
        self.act_about = QAction(self)
        self.act_about.triggered.connect(self._about)
        self.help_menu.addAction(self.act_about)

    # -- theme / language -------------------------------------------------
    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        self.tab_bar.restyle(p)
        for tab in self._built.values():
            if hasattr(tab, "restyle"):
                tab.restyle(p)
        action = self.theme_actions.get(p.key)
        if action:
            action.setChecked(True)

    def retranslate(self) -> None:
        self.setWindowTitle(t("app_title"))
        for i, key in enumerate(TAB_KEYS):
            self.tabs.setTabText(i, t(key))

        self.study_menu.setTitle(t("menu_study"))
        self.act_note.setText(t("menu_new_note"))
        self.act_weak.setText(t("menu_weak_note"))
        self.act_sent_note.setText(t("menu_sentence_note"))
        self.act_save.setText(t("menu_save_current"))
        self.act_speak.setText(t("menu_speak"))
        self.act_hide.setText(t("menu_hide_tray"))

        self.view_menu.setTitle(t("menu_view"))
        self.theme_menu.setTitle(t("menu_theme"))
        for key, action in self.theme_actions.items():
            p = theme.PALETTES[key]
            action.setText(p.name_en if i18n.language() == "en" else p.name_ko)
        self.voice_menu.setTitle(t("menu_voice"))
        for key, action in self.voice_actions.items():
            action.setText(t({"female": "voice_female", "male": "voice_male",
                              "off": "voice_off"}[key]))
        self.lang_menu.setTitle(t("menu_language"))

        self.data_menu.setTitle(t("menu_data"))
        self.act_open_data.setText(t("menu_open_data"))
        self.act_open_folder.setText(t("menu_open_folder"))
        self.help_menu.setTitle(t("menu_help"))
        self.act_about.setText(t("menu_about"))

        for tab in self._built.values():
            if hasattr(tab, "retranslate"):
                tab.retranslate()
        self.refresh_status()

    # -- actions ---------------------------------------------------------
    def _save_current_tab(self) -> None:
        tab = self._built.get(self.tabs.currentIndex())
        if isinstance(tab, EntryTab):
            tab.save_current()

    def _speak_current_tab(self) -> None:
        tab = self._built.get(self.tabs.currentIndex())
        if isinstance(tab, EntryTab):
            tab.speak_current()
        elif isinstance(tab, ReadingTab):
            tab._speak_selected()

    def _set_voice(self, key: str) -> None:
        if key == "off":
            tts.set_enabled(False)
            tts.stop()
        else:
            tts.set_enabled(True)
            tts.set_gender(key)
        for name, action in self.voice_actions.items():
            action.setChecked(name == key)

    def _add_sentence(self, english: str, korean: str) -> None:
        repo.save_row("sentences", {
            "english": english, "korean": korean,
            "source": t("tab_reading"), "studied_on": repo.today(),
        })
        if 2 in self._built:
            self._built[2].reload()
        self.refresh_status()

    def _open_data_folder(self) -> None:
        import os
        os.startfile(db.default_data_dir())     # noqa: S606 -- Windows shell open

    def _about(self) -> None:
        QMessageBox.about(self, "Engo", t(
            "about_body", path=db.db_path(),
            device=db.get_meta("device_name"), id=db.device_id()))

    def refresh_status(self) -> None:
        s = repo.stats()
        self.status_label.setText(t(
            "status", expr=s["expressions"], sent=s["sentences"],
            gram=s["grammar"], **{"pass": s["passages"]},
            today=s["today"], weak=s["weak"], notes=self._sticky_count()))

    def reload_all(self) -> None:
        for tab in self._built.values():
            if hasattr(tab, "reload"):
                tab.reload()
        self.refresh_status()

    def flush(self) -> None:
        for tab in self._built.values():
            if hasattr(tab, "flush"):
                tab.flush()

    # -- lifecycle -------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Needs a real window handle, so it cannot be done in __init__.
        round_corners(self)

    def prepare_quit(self) -> None:
        self._quitting = True

    def closeEvent(self, event) -> None:
        self.flush()
        if self._quitting:
            super().closeEvent(event)
            return
        # Closing the window does not quit: the tray icon and any open sticky
        # notes keep running, and the window itself is torn down so its
        # widgets stop costing memory until it is opened again.
        event.ignore()
        self.hide()
        self.closedToTray.emit()


