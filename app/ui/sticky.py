"""2. 복습 메모지 — frameless sticky note windows.

Memory notes: a sticky is a plain QWidget in the *same* process as the main
window, so opening one costs a few hundred KB, not a new interpreter or a new
browser engine. Item widgets are rebuilt only on refresh, and the query behind
them is capped, so a note can never balloon.

Geometry, colour and options live in the local-only `sticky_windows` table --
never exported, because another machine's screen layout is not this machine's.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizeGrip,
    QSlider, QVBoxLayout, QWidget,
)

from .. import repo, theme, tts
from ..i18n import t
from .common import english_font, round_menu

# 메모지 색은 팔레트의 파스텔 액센트를 그대로 쓴다 -- 테마를 바꾸면 메모지도 따라간다.
COLOR_KEYS = ("c1", "c2", "c3", "c4", "c5", "c6")
COLOR_NAMES_KO = ("라벤더", "민트", "피치", "레몬", "로즈", "스카이")
COLOR_NAMES_EN = ("Lavender", "Mint", "Peach", "Lemon", "Rose", "Sky")

# How many items one note materialises at a time, and the largest number it
# will bother counting for the footer.
BATCH = 30
BATCH_CEILING = 999


def note_colors(p: theme.Palette, key: str) -> tuple[str, str, str]:
    """(background, border, text) for a note colour key."""
    index = COLOR_KEYS.index(key) if key in COLOR_KEYS else 0
    if not p.accents:
        return p.surface, p.border, p.text
    i = index % len(p.accents)
    return p.accents[i], p.accent_borders[i], p.accent_text


def color_name(key: str) -> str:
    from .. import i18n
    index = COLOR_KEYS.index(key) if key in COLOR_KEYS else 0
    names = COLOR_NAMES_EN if i18n.language() == "en" else COLOR_NAMES_KO
    return names[index % len(names)]


def kind_name(kind: str) -> str:
    return t("kind_sentences" if kind == "sentences" else "kind_expressions")


class ReviewItem(QFrame):
    """One row: English always visible, Korean hidden until clicked.

    Kept deliberately thin. An earlier version gave every item its own
    answer buttons up front, which put ~500 widgets in a single note and cost
    over 13MB per note -- unacceptable for a window meant to sit on screen all
    day. The buttons are now built on first reveal, so an unrevealed item is
    just a frame and two labels.
    """

    answered = Signal(str, bool)   # row_id, correct

    def __init__(self, data: dict, kind: str, hide_answer: bool, colors,
                 dark: bool = False, parent=None):
        super().__init__(parent)
        self.row_id = data["id"]
        self.kind = kind
        self._korean = data.get("korean", "") or t("empty_meaning")
        self._revealed = not hide_answer
        self._buttons: QWidget | None = None
        _bg, self._border, self._fg = colors
        self._dark = dark

        # On a dark note the text is light, so an opaque white overlay would
        # put light text on a near-white panel. Tint towards white only far
        # enough to lift the card off the background.
        self._overlay = "rgba(255,255,255,0.07)" if dark else "rgba(255,255,255,0.5)"
        self._muted = ("rgba(255,255,255,0.42)" if dark else "rgba(0,0,0,0.35)")
        self._btn_bg = ("rgba(255,255,255,0.12)" if dark
                        else "rgba(255,255,255,0.75)")
        self._btn_hover = ("rgba(255,255,255,0.22)" if dark else "#ffffff")

        self.setStyleSheet(
            f"ReviewItem {{ background: {self._overlay};"
            f" border: 1px solid {self._border}; border-radius: 10px; }}"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(11, 9, 11, 9)
        self._layout.setSpacing(3)

        self._english_text = data.get("english", "")
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        self.english = QLabel(self._english_text)
        self.english.setFont(english_font(10, bold=True))
        self.english.setWordWrap(True)
        self.english.setStyleSheet(
            f"color: {self._fg}; background: transparent; border: none;")
        top.addWidget(self.english, 1)

        # Listening before revealing the meaning is the point of a review
        # note, so the speaker sits next to the English, not behind a reveal.
        if tts.installed():
            speak = QPushButton("🔊")
            speak.setFixedSize(22, 22)
            speak.setCursor(QCursor(Qt.PointingHandCursor))
            speak.setToolTip(t("speak_tip"))
            hover = ("rgba(255,255,255,0.14)" if dark
                     else "rgba(255,255,255,0.7)")
            speak.setStyleSheet(
                "QPushButton { border: none; background: transparent;"
                " padding: 0; margin: 0; min-width: 0; font-size: 10pt; }"
                f" QPushButton:hover {{ background: {hover};"
                f" border-radius: 6px; }}")
            speak.clicked.connect(lambda: tts.speak(self._english_text))
            top.addWidget(speak, 0, Qt.AlignTop)
        self._layout.addLayout(top)

        self.korean = QLabel()
        self.korean.setWordWrap(True)
        self.korean.setCursor(QCursor(Qt.PointingHandCursor))
        self._layout.addWidget(self.korean)

        self._render()

    def _ensure_buttons(self) -> None:
        if self._buttons is not None:
            return
        self._buttons = QWidget(self)
        row = QHBoxLayout(self._buttons)
        row.setContentsMargins(0, 3, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)

        style = ("QPushButton { border: 1px solid %s; border-radius: 10px;"
                 " padding: 2px 11px; font-size: 8pt;"
                 " background: %s; color: %s; }"
                 " QPushButton:hover { background: %s; }"
                 % (self._border, self._btn_bg, self._fg, self._btn_hover))
        known = QPushButton(t("know"))
        known.setStyleSheet(style)
        known.clicked.connect(lambda: self.answered.emit(self.row_id, True))
        row.addWidget(known)

        unknown = QPushButton(t("unsure"))
        unknown.setStyleSheet(style)
        unknown.clicked.connect(lambda: self.answered.emit(self.row_id, False))
        row.addWidget(unknown)
        self._layout.addWidget(self._buttons)

    def _render(self) -> None:
        if self._revealed:
            self.korean.setText(self._korean)
            self.korean.setStyleSheet(
                f"color: {self._fg}; background: transparent; border: none;")
            self._ensure_buttons()
        else:
            self.korean.setText(t("reveal"))
            self.korean.setStyleSheet(
                f"color: {self._muted}; background: transparent; border: none;"
                f" font-style: italic;")
        if self._buttons is not None:
            self._buttons.setVisible(self._revealed)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._revealed = not self._revealed
            self._render()
        super().mousePressEvent(event)

    def reveal(self, on: bool) -> None:
        self._revealed = on
        self._render()


class StickySettings(QDialog):
    def __init__(self, state: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("sticky_settings"))
        self.setMinimumWidth(360)

        form = QFormLayout(self)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(10)

        self.kind = QComboBox()
        for key in ("expressions", "sentences"):
            self.kind.addItem(kind_name(key), key)
        index = self.kind.findData(state.get("kind", "expressions"))
        self.kind.setCurrentIndex(max(index, 0))
        form.addRow(t("what_to_review"), self.kind)

        self.query = QComboBox()
        self.query.setEditable(True)
        self._fill_scopes(state.get("kind", "expressions"),
                          state.get("query", "today"))
        # The date/tag lists belong to the chosen kind; switching from
        # expressions to sentences must not keep offering expression tags.
        self.kind.currentIndexChanged.connect(
            lambda _: self._fill_scopes(self.kind.currentData(),
                                        self.query.currentData() or "today"))
        form.addRow(t("scope"), self.query)

        self.color = QComboBox()
        for key in COLOR_KEYS:
            self.color.addItem(color_name(key), key)
        index = self.color.findData(state.get("color", "c1"))
        self.color.setCurrentIndex(max(index, 0))
        form.addRow(t("colour"), self.color)

        self.hide_answer = QCheckBox(t("hide_meaning"))
        self.hide_answer.setChecked(bool(state.get("hide_answer", 1)))
        form.addRow("", self.hide_answer)

        self.on_top = QCheckBox(t("always_on_top"))
        self.on_top.setChecked(bool(state.get("on_top", 0)))
        form.addRow("", self.on_top)

        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(40, 100)
        self.opacity.setValue(int(state.get("opacity", 100)))
        self.opacity_label = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%"))
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_label)
        form.addRow(t("opacity"), opacity_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Ok).setText(t("ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _fill_scopes(self, kind: str, current: str) -> None:
        self.query.blockSignals(True)
        self.query.clear()
        self.query.addItem(t("scope_today"), "today")
        self.query.addItem(t("scope_weak_long"), "weak")
        self.query.addItem(t("scope_all"), "")
        for date, count in repo.study_dates(kind, limit=30):
            self.query.addItem(f"{date} ({count})", f"date:{date}")
        for tag in repo.all_tags(kind):
            self.query.addItem(f"{t('tag')}: {tag}", f"tag:{tag}")
        index = self.query.findData(current)
        if index >= 0:
            self.query.setCurrentIndex(index)
        else:
            self.query.setCurrentText(current)
        self.query.blockSignals(False)

    def values(self) -> dict:
        data = self.query.currentData()
        query = data if data is not None else self.query.currentText().strip()
        return {
            "kind": self.kind.currentData(),
            "query": query,
            "color": self.color.currentData(),
            "hide_answer": 1 if self.hide_answer.isChecked() else 0,
            "on_top": 1 if self.on_top.isChecked() else 0,
            "opacity": self.opacity.value(),
        }


class StickyNote(QWidget):
    """A frameless, draggable, resizable note window."""

    closed = Signal(str)

    def __init__(self, state: dict, palette: theme.Palette, parent=None):
        super().__init__(parent)
        self.state = dict(state)
        self.palette = palette
        self._drag_offset: QPoint | None = None
        self._items: list[QWidget] = []
        self._batch_total = 0

        # Qt.Tool keeps it off the taskbar; the note belongs to the app, not
        # to the window list the user alt-tabs through.
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        # The note paints a rounded panel, but the window behind it is a real
        # opaque rectangle -- so the area outside the curve stayed filled and
        # read as a square border around the rounded note. Translucency lets
        # the corners actually cut away.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(t("sticky"))

        self._build()
        self._apply_state()
        self.refresh()

        # Geometry writes are debounced: dragging a window fires hundreds of
        # move events and each one would otherwise be a database round trip.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._persist_geometry)

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.frame = QFrame()
        self.frame.setObjectName("note")
        outer.addWidget(self.frame)

        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        inner.addWidget(self._build_titlebar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 6, 10, 10)
        self.body_layout.setSpacing(7)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)
        inner.addWidget(self.scroll, 1)

        inner.addWidget(self._build_footer())

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(30)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 5, 0)
        layout.setSpacing(2)

        self.title_label = QLabel()
        font = self.title_label.font()
        font.setBold(True)
        font.setPointSize(9)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label, 1)

        self.reveal_btn = self._icon_button("👁", t("tip_reveal"), self.toggle_reveal)
        layout.addWidget(self.reveal_btn)
        layout.addWidget(self._icon_button("⟳", t("tip_refresh"), self.refresh))
        layout.addWidget(self._icon_button("⚙", t("tip_settings"), self.open_settings))
        layout.addWidget(self._icon_button("✕", t("tip_close"), self.close))
        self.titlebar = bar
        return bar

    def _icon_button(self, text: str, tip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(23, 23)
        button.setToolTip(tip)
        button.setCursor(QCursor(Qt.PointingHandCursor))
        button.setFlat(True)
        button.clicked.connect(slot)
        return button

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(24)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 3, 3)
        layout.setSpacing(4)

        self.count_label = QLabel()
        layout.addWidget(self.count_label, 1)

        grip = QSizeGrip(bar)
        grip.setFixedSize(14, 14)
        layout.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        return bar

    # -- appearance ------------------------------------------------------
    def _apply_state(self) -> None:
        bg, border, fg = note_colors(self.palette, self.state.get("color", "c1"))
        # `padding: 0` is load-bearing, not tidiness. The app-wide stylesheet
        # gives every QPushButton padding, and a rule here that does not reset
        # it leaves these 23x23 title bar buttons with no room for their glyph
        # -- Qt clips the text away and they render as blank squares.
        # The hover fill must dim, not lighten, on the dark palette: a near-
        # opaque white wash behind light-coloured glyphs made the buttons
        # vanish under the cursor on Midnight.
        hover = ("rgba(255,255,255,0.14)" if self.palette.dark
                 else "rgba(255,255,255,0.7)")
        self.frame.setStyleSheet(
            f"QFrame#note {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 12px; }}"
            f" QLabel {{ color: {fg}; background: transparent; border: none; }}"
            f" QPushButton {{ border: none; background: transparent; color: {fg};"
            f" font-size: 11pt; padding: 0; margin: 0; min-width: 0; }}"
            f" QPushButton:hover {{ background: {hover};"
            f" border-radius: 6px; }}"
            f" QScrollArea {{ background: transparent; border: none; }}"
        )
        self.body.setStyleSheet("background: transparent;")
        faint = "rgba(255,255,255,0.5)" if self.palette.dark else "rgba(0,0,0,0.45)"
        self.count_label.setStyleSheet(f"font-size: 8pt; color: {faint};")

        on_top = bool(self.state.get("on_top", 0))
        flags = Qt.Tool | Qt.FramelessWindowHint
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        if flags != self.windowFlags():
            visible = self.isVisible()
            self.setWindowFlags(flags)
            # setWindowFlags recreates the native window and drops the
            # attribute with it, so it has to be set again or the square
            # background comes back the first time "always on top" is toggled.
            self.setAttribute(Qt.WA_TranslucentBackground)
            if visible:
                self.show()

        self.setWindowOpacity(max(40, int(self.state.get("opacity", 100))) / 100)
        self.setGeometry(
            int(self.state.get("x", 120)), int(self.state.get("y", 120)),
            int(self.state.get("w", 330)), int(self.state.get("h", 400)),
        )
        self._ensure_on_screen()

    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        self._apply_state()
        self.refresh()

    def _ensure_on_screen(self) -> None:
        """A note restored from a different monitor layout must not vanish."""
        if QApplication.screenAt(self.geometry().center()) is not None:
            return
        primary = QApplication.primaryScreen()
        if primary is None:
            return
        area = primary.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)

    def _scope_label(self) -> str:
        query = self.state.get("query", "today")
        if query == "today":
            return t("scope_today")
        if query == "weak":
            return t("scope_weak")
        if query.startswith("date:"):
            return query[5:]
        if query.startswith("tag:"):
            return f"#{query[4:]}"
        return t("scope_all")

    # -- data ------------------------------------------------------------
    def refresh(self) -> None:
        kind = self.state.get("kind", "expressions")
        query = self.state.get("query", "today")

        kwargs: dict = {}
        if query == "today":
            kwargs["studied_on"] = repo.today()
        elif query == "weak":
            kwargs["only_weak"] = True
        elif query.startswith("date:"):
            kwargs["studied_on"] = query[5:]
        elif query.startswith("tag:"):
            kwargs["tag"] = query[4:]

        # A note shows a batch, not a whole deck. Items are ordered weakest
        # first and answered ones disappear, so ⟳ pulls the next batch --
        # which is both better review practice and a hard cap on widget count.
        self._batch_total = len(repo.review_items(kind, limit=BATCH_CEILING, **kwargs))
        rows = repo.review_items(kind, limit=BATCH, **kwargs)
        colors = note_colors(self.palette, self.state.get("color", "c1"))
        hide = bool(self.state.get("hide_answer", 1))

        for item in self._items:
            item.setParent(None)
            item.deleteLater()
        self._items.clear()

        for row in rows:
            item = ReviewItem(row, kind, hide, colors, self.palette.dark, self.body)
            item.answered.connect(self._on_answered)
            self.body_layout.insertWidget(self.body_layout.count() - 1, item)
            self._items.append(item)

        if not rows:
            empty = QLabel(t("sticky_empty_today") if query == "today"
                           else t("sticky_empty_other"))
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {'rgba(255,255,255,0.45)' if self.palette.dark else 'rgba(0,0,0,0.42)'};"
                f" font-size: 9pt;")
            self.body_layout.insertWidget(0, empty)
            self._items.append(empty)

        self.title_label.setText(f"{kind_name(kind)} · {self._scope_label()}")
        self._update_count(len(rows))

    def _update_count(self, shown: int) -> None:
        if self._batch_total > shown:
            self.count_label.setText(
                t("batch_status", shown=shown, total=self._batch_total))
        else:
            self.count_label.setText(t("count_items", n=shown))

    def _on_answered(self, row_id: str, correct: bool) -> None:
        repo.mark_reviewed(self.state.get("kind", "expressions"), row_id, correct)
        for item in self._items:
            if isinstance(item, ReviewItem) and item.row_id == row_id:
                item.setParent(None)
                item.deleteLater()
                self._items.remove(item)
                break
        remaining = sum(1 for i in self._items if isinstance(i, ReviewItem))
        self._batch_total = max(0, self._batch_total - 1)
        self.count_label.setText(t("remaining", n=remaining))

    def toggle_reveal(self) -> None:
        items = [i for i in self._items if isinstance(i, ReviewItem)]
        if not items:
            return
        target = not items[0]._revealed
        for item in items:
            item.reveal(target)

    def open_settings(self) -> None:
        dialog = StickySettings(self.state, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.state.update(dialog.values())
        self._apply_state()
        self.refresh()
        self._persist_geometry()

    # -- window behaviour ------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and event.position().y() <= 30:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        # A frameless window has no title-bar ✕; Esc is the reflex that
        # should work everywhere a window can be dismissed.
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = round_menu(QMenu(self))
        menu.addAction(t("tip_reveal"), self.toggle_reveal)
        menu.addAction(t("tip_refresh"), self.refresh)
        menu.addSeparator()
        top = menu.addAction(t("always_on_top_short"))
        top.setCheckable(True)
        top.setChecked(bool(self.state.get("on_top", 0)))
        top.triggered.connect(self._toggle_on_top)
        colors = round_menu(menu.addMenu(t("colour")))
        for key in COLOR_KEYS:
            colors.addAction(color_name(key), lambda k=key: self._set_color(k))
        menu.addSeparator()
        menu.addAction(t("settings_dots"), self.open_settings)
        menu.addAction(t("close_this_note"), self.close)
        menu.exec(event.globalPos())

    def _toggle_on_top(self, checked: bool) -> None:
        self.state["on_top"] = 1 if checked else 0
        self._apply_state()
        self.show()
        self._persist_geometry()

    def _set_color(self, key: str) -> None:
        self.state["color"] = key
        self._apply_state()
        self.refresh()
        self._persist_geometry()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "_save_timer"):
            self._save_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_save_timer"):
            self._save_timer.start()

    def _persist_geometry(self) -> None:
        """Save position/size/options. Deliberately does not touch `open` --
        whether the note should come back next launch is the caller's call."""
        geometry = self.geometry()
        self.state.update({
            "x": geometry.x(), "y": geometry.y(),
            "w": geometry.width(), "h": geometry.height(),
        })
        repo.sticky_save(self.state)

    def closeEvent(self, event) -> None:
        # Closed by the user: stay closed on the next launch.
        self._persist_geometry()
        self.state["open"] = 0
        repo.sticky_save(self.state)
        self.closed.emit(self.state["id"])
        super().closeEvent(event)


class StickyManager:
    """Owns every open note and reopens the ones that were open last time."""

    def __init__(self, palette: theme.Palette):
        self.palette = palette
        self.notes: dict[str, StickyNote] = {}

    def restore(self) -> int:
        for state in repo.sticky_list(open_only=True):
            self._spawn(state)
        return len(self.notes)

    def open_new(self, kind: str = "expressions", query: str = "today",
                 tag: str = "") -> StickyNote:
        if tag:
            query = f"tag:{tag}"
        offset = 28 * (len(self.notes) % 8)
        state = {
            "id": None, "kind": kind, "query": query,
            "x": 150 + offset, "y": 140 + offset, "w": 340, "h": 420,
            "hide_answer": 1, "on_top": 0, "opacity": 100,
            "color": COLOR_KEYS[len(self.notes) % len(COLOR_KEYS)], "open": 1,
        }
        state["id"] = repo.sticky_save(state)
        return self._spawn(state)

    def _spawn(self, state: dict) -> StickyNote:
        note = StickyNote(state, self.palette)
        note.closed.connect(self._on_closed)
        self.notes[state["id"]] = note
        note.show()
        note.raise_()
        return note

    def _on_closed(self, sticky_id: str) -> None:
        self.notes.pop(sticky_id, None)

    def refresh_all(self) -> None:
        for note in self.notes.values():
            note.refresh()

    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        for note in self.notes.values():
            note.restyle(p)

    def rebuild(self) -> None:
        """Recreate every open note -- used after a language change, since the
        notes hold translated text that is baked in at build time."""
        states = [dict(n.state) for n in self.notes.values()]
        for note in list(self.notes.values()):
            note.closed.disconnect()
            note.hide()
            note.deleteLater()
        self.notes.clear()
        for state in states:
            self._spawn(state)

    def close_all(self, remember: bool = True) -> None:
        """remember=True is the quit path: notes reopen next launch.
        remember=False is the user saying 'close these', so they stay closed."""
        for note in list(self.notes.values()):
            if remember:
                note._persist_geometry()
                note.state["open"] = 1
                repo.sticky_save(note.state)
                note.closed.disconnect()
                note.hide()
                note.deleteLater()
            else:
                note.close()      # closeEvent records open = 0
        self.notes.clear()

    @property
    def count(self) -> int:
        return len(self.notes)
