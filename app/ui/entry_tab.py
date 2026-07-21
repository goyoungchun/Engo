"""Generic list + editor tab.

Backs three of the five features, which differ only in their columns and form
fields:
  1. 영어 표현 정리      -> expressions
  3. 외우고 싶은 문장    -> sentences
  4. 문법 정리           -> grammar
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableView, QVBoxLayout,
    QWidget,
)

from .. import db, repo, theme, tts
from ..i18n import t
from .common import (
    ROW_NUMBER, Card, Column, Field, LazyTableModel, TagCompleter,
    apply_placeholder, editor_value, hint_label, make_editor, scrollable,
    set_completions, set_editor_value, whole_field_completer,
)

# 편집기 패널의 왼쪽 여백. 위쪽 툴바의 태그 칸도 같은 값을 써야 줄이 맞는다.
EDITOR_LEFT_MARGIN = 14

SPECS: dict[str, dict[str, Any]] = {
    "expressions": {
        "title_key": "expr_title",
        "edit_key": "expr_edit",
        "new_key": "expr_new",
        "columns": [
            Column(ROW_NUMBER, "col_no", 42, centred=True),
            Column("english", "col_english", 300, stretch=True),
            Column("korean", "col_korean", 260, stretch=True),
            Column("tags", "tags", 110),
            Column("studied_on", "col_studied_on", 100, centred=True),
            Column("box", "col_box", 90, centred=True),
        ],
        "fields": [
            Field("english", "f_english", "text", 66, "ph_english"),
            Field("korean", "f_korean", "text", 66, "ph_korean"),
            Field("note", "f_note", "text", 84, "ph_note"),
            Field("source", "f_source", "line", 0, "ph_source"),
            Field("tags", "tags", "line", 0, "ph_tags"),
            Field("studied_on", "f_studied_on", "date"),
        ],
    },
    "sentences": {
        "title_key": "sent_title",
        "edit_key": "sent_edit",
        "new_key": "sent_new",
        "columns": [
            Column(ROW_NUMBER, "col_no", 42, centred=True),
            Column("starred", "col_star", 34, centred=True),
            Column("english", "col_source_text", 330, stretch=True),
            Column("korean", "col_translation", 270, stretch=True),
            Column("tags", "tags", 110),
            Column("studied_on", "col_registered", 100, centred=True),
            Column("box", "col_box", 90, centred=True),
        ],
        "fields": [
            Field("english", "f_original", "text", 84, "ph_sent_en"),
            Field("korean", "f_translation", "text", 84, "ph_sent_ko"),
            Field("note", "f_note", "text", 76, "ph_sent_note"),
            Field("source", "f_source", "line", 0, "ph_source"),
            Field("tags", "tags", "line", 0, "ph_tags"),
            Field("studied_on", "f_registered", "date"),
        ],
        "extra_check": ("starred", "starred"),
    },
    "grammar": {
        "title_key": "gram_title",
        "edit_key": "gram_edit",
        "new_key": "gram_new",
        "columns": [
            Column(ROW_NUMBER, "col_no", 42, centred=True),
            Column("title", "col_point", 260, stretch=True),
            Column("body", "col_explanation", 410, stretch=True),
            Column("tags", "tags", 110),
            Column("studied_on", "col_written_on", 100, centred=True),
        ],
        "fields": [
            Field("title", "f_point", "text", 58, "ph_point"),
            Field("body", "f_explanation", "text", 140, "ph_explanation"),
            Field("examples", "f_examples", "text", 104, "ph_examples"),
            Field("tags", "tags", "line", 0, "ph_gram_tags"),
            Field("studied_on", "f_written_on", "date"),
        ],
    },
}


class EntryTab(QWidget):
    """List on the left, editor on the right, filters on top."""

    dataChanged = Signal()

    def __init__(self, table: str, palette: theme.Palette, parent=None):
        super().__init__(parent)
        self.table = table
        self.spec = SPECS[table]
        self.palette = palette
        self._current_id: str | None = None
        self._dirty = False
        self._loading = False
        self._editors: dict[str, QWidget] = {}
        self._labels: dict[str, QLabel] = {}
        self._check: QCheckBox | None = None
        # Set up front: the table's first resize fires the event filter while
        # _build() is still running, before the editor panel exists.
        self.search_box: QWidget | None = None
        self.action_box: QWidget | None = None
        self.editor_panel: QWidget | None = None

        self._build()
        self.restyle(palette)
        self.retranslate()
        self.reload()

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(12)

        outer.addLayout(self._build_filters())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(14)
        self.splitter.addWidget(self._build_table())
        self.splitter.addWidget(self._build_editor())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([620, 430])
        self._filter_bar.setSpacing(self.splitter.handleWidth())
        outer.addWidget(self.splitter, 1)

        self.status = hint_label()
        outer.addWidget(self.status)

    def _build_filters(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        # 위쪽 줄을 아래쪽 두 칸과 같은 폭으로 나눈다.
        #   왼쪽: 검색            -> 아래의 표와 같은 너비
        #   오른쪽: 태그·추가·삭제 -> 아래의 편집기와 같은 너비
        self.search_box = QWidget()
        search_row = QHBoxLayout(self.search_box)
        search_row.setContentsMargins(0, 0, 0, 0)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(80)
        self.search.textChanged.connect(self.reload)
        search_row.addWidget(self.search)
        bar.addWidget(self.search_box)

        self.action_box = QWidget()
        action_row = QHBoxLayout(self.action_box)
        # 편집기 패널과 같은 왼쪽 여백이라야 아래 라벨과 줄이 맞는다.
        action_row.setContentsMargins(EDITOR_LEFT_MARGIN, 0, 0, 0)
        action_row.setSpacing(8)

        self.tag_label = QLabel()
        action_row.addWidget(self.tag_label)
        self.tag_filter = QComboBox()
        self.tag_filter.setMinimumWidth(120)
        self.tag_filter.currentIndexChanged.connect(self.reload)
        action_row.addWidget(self.tag_filter)
        action_row.addStretch(1)

        self.new_btn = QPushButton()
        self.new_btn.setObjectName("primary")
        self.new_btn.clicked.connect(self.new_entry)
        action_row.addWidget(self.new_btn)

        self.del_btn = QPushButton()
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.delete_selected)
        action_row.addWidget(self.del_btn)

        # Stretches into whatever is left. Deliberately *not* a second fixed
        # width: fixing both boxes made the row's minimum width fight the
        # splitter for space, and the two kept resizing each other until the
        # stack overflowed.
        bar.addWidget(self.action_box, 1)
        self._filter_bar = bar
        return bar

    def _build_table(self) -> QWidget:
        self.model = LazyTableModel(self.table, self.spec["columns"], self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setShowGrid(True)
        self.view.setGridStyle(Qt.SolidLine)
        self.view.setWordWrap(False)
        self.view.verticalHeader().setDefaultSectionSize(38)
        self.view.verticalHeader().setVisible(False)
        self.view.setFrameShape(QTableView.NoFrame)

        header = self.view.horizontalHeader()
        header.setHighlightSections(False)
        for i, col in enumerate(self.spec["columns"]):
            self.view.setColumnWidth(i, col.width)
            if col.stretch:
                header.setSectionResizeMode(i, QHeaderView.Interactive)
        header.setStretchLastSection(False)

        self.view.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self.view.doubleClicked.connect(lambda _: self._focus_first_editor())
        self.view.installEventFilter(self)

        # Delete key deletes the selected rows -- WidgetShortcut so typing
        # Delete inside the editor fields is unaffected.
        from PySide6.QtGui import QKeySequence, QShortcut
        shortcut = QShortcut(QKeySequence.Delete, self.view)
        shortcut.setContext(Qt.WidgetShortcut)
        shortcut.activated.connect(self.delete_selected)

        # The table draws its own rounded border, so wrapping it in a card put
        # a border inside a border. These tabs hold nothing but the table.
        return self.view

    def _build_editor(self) -> QWidget:
        panel = QWidget()
        self.editor_panel = panel
        panel.installEventFilter(self)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(EDITOR_LEFT_MARGIN, 0, 0, 0)
        outer.setSpacing(0)

        card = Card(padding=18)
        self.editor_card = card
        # Scrolled, not squeezed. The text boxes have fixed heights, so when
        # the window is too short Qt would otherwise lay them on top of each
        # other -- which is exactly what the 원문/번역/메모 fields did.
        outer.addWidget(scrollable(card))

        layout = card.body

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(16)
        for field in self.spec["fields"]:
            widget = make_editor(field)
            self._editors[field.key] = widget
            self._watch(widget)
            label = QLabel()
            self._labels[field.key] = label
            form.addRow(label, widget)
        layout.addLayout(form)

        # Autocomplete the two fields that get retyped the most. Source is one
        # value, so it completes the whole line; tags are comma-separated, so
        # the tag completer only finishes the segment after the last comma.
        # Models are filled in _refresh_tags, which runs on every reload.
        self._source_completer = None
        self._tags_completer = None
        if "source" in self._editors:
            self._source_completer = whole_field_completer(self)
            self._editors["source"].setCompleter(self._source_completer)
        if "tags" in self._editors:
            self._tags_completer = TagCompleter(self)
            self._editors["tags"].setCompleter(self._tags_completer)

        extra = self.spec.get("extra_check")
        if extra:
            self._check = QCheckBox()
            self._check.stateChanged.connect(self._mark_dirty)
            layout.addWidget(self._check)
        layout.addStretch(1)

        # Outside the scroll area on purpose: on a short window the form
        # scrolls, and a Save button that scrolls out of reach is worse than
        # no button at all.
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 10, 0, 0)
        buttons.setSpacing(10)

        # Parent given explicitly at construction. A parentless widget that is
        # made visible becomes a top-level window of its own, which flashed a
        # stray 46x36 button on screen every time a tab was built. Adding it
        # to `buttons` first is not enough -- that layout is not installed on
        # a widget yet, so addWidget does not reparent anything.
        self.speak_btn = QPushButton("🔊", panel)
        self.speak_btn.setObjectName("speak")
        self.speak_btn.setFixedWidth(46)
        self.speak_btn.clicked.connect(self.speak_current)
        self.speak_btn.setVisible(tts.installed())
        buttons.addWidget(self.speak_btn)

        self.dirty_label = hint_label()
        buttons.addWidget(self.dirty_label, 1)

        self.save_btn = QPushButton()
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save_current)
        buttons.addWidget(self.save_btn)

        self.revert_btn = QPushButton()
        self.revert_btn.clicked.connect(lambda: self._load_row(self._current_id))
        buttons.addWidget(self.revert_btn)
        outer.addLayout(buttons)
        return panel

    def _watch(self, widget: QWidget) -> None:
        for signal_name in ("textChanged", "dateChanged"):
            signal = getattr(widget, signal_name, None)
            if signal is not None:
                signal.connect(self._mark_dirty)
                break

    # -- theming / language ----------------------------------------------
    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        self.editor_card.restyle(p)
        self.model.restyle(p)

    def retranslate(self) -> None:
        self.search.setPlaceholderText(t("ph_search"))
        self.tag_label.setText(t("tag"))
        self.new_btn.setText(t("add_new"))
        self.del_btn.setText(t("delete"))
        self.save_btn.setText(t("save_shortcut"))
        self.revert_btn.setText(t("revert"))
        self.speak_btn.setToolTip(t("speak_tip"))
        for field in self.spec["fields"]:
            self._labels[field.key].setText(t(field.label_key))
            apply_placeholder(self._editors[field.key], field)
        if self._check:
            self._check.setText(t(self.spec["extra_check"][1]))
        self._refresh_tags()
        self.model.restyle(self.palette)
        self._update_status()
        self.dirty_label.setText(t("unsaved") if self._dirty else "")

    # -- layout sync ------------------------------------------------------
    def _sync_widths(self, *_) -> None:
        """Pin the search box to the table's width; the rest follows."""
        if self.search_box is None or self.view.width() <= 0:
            return
        if self.search_box.width() != self.view.width():
            self.search_box.setFixedWidth(self.view.width())

    def eventFilter(self, obj, event) -> bool:
        # Driven off the panes' own resize rather than the splitter's
        # splitterMoved signal: that signal only fires for user drags, so
        # setSizes() and the initial layout would silently leave things
        # misaligned. Watching the widgets themselves covers every cause.
        if event.type() == QEvent.Resize and obj in (self.view, self.editor_panel):
            self._sync_widths()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_widths()

    # -- state -----------------------------------------------------------
    def _tag(self) -> str:
        return "" if self.tag_filter.currentIndex() <= 0 else self.tag_filter.currentText()

    def _mark_dirty(self, *_) -> None:
        if self._loading:
            return
        self._dirty = True
        self.dirty_label.setText(t("unsaved"))

    def _clear_dirty(self) -> None:
        self._dirty = False
        self.dirty_label.setText("")

    def _focus_first_editor(self) -> None:
        if self.spec["fields"]:
            self._editors[self.spec["fields"][0].key].setFocus()

    def _update_status(self, extra: str = "") -> None:
        text = t("count_items", n=self.model.total)
        if self.search.text():
            text += "  ·  " + t("search_result")
        if extra:
            text += "  ·  " + extra
        self.status.setText(text)

    # -- loading ---------------------------------------------------------
    def reload(self) -> None:
        self._refresh_tags()
        self.model.refresh(search=self.search.text(), tag=self._tag())
        self._update_status()
        if self._current_id:
            row = self.model.index_of(self._current_id)
            if row >= 0:
                self.view.selectRow(row)
                return
        if self.model.total and self._current_id is None and not self._dirty:
            self.view.selectRow(0)
        elif not self.model.total and not self._dirty:
            # Only blank the form when there is nothing unsaved in it --
            # otherwise typing a search term would erase what was being typed.
            self._clear_editor()

    def _refresh_tags(self) -> None:
        current = self.tag_filter.currentText()
        tags = repo.all_tags(self.table)
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem(t("all"))
        self.tag_filter.addItems(tags)
        if current in tags:
            self.tag_filter.setCurrentText(current)
        self.tag_filter.blockSignals(False)

        # Keep the editor autocompletion in step with what has been entered.
        if self._tags_completer is not None:
            set_completions(self._tags_completer, tags)
        if self._source_completer is not None:
            set_completions(self._source_completer, repo.all_sources(self.table))

    def _on_row_changed(self, current, previous) -> None:
        # Also saves when _current_id is None: that is a half-typed new entry,
        # and clicking a row must not throw it away.
        if self._dirty:
            self.save_current(silent=True)
        row_id = self.model.row_id(current.row()) if current.isValid() else None
        self._load_row(row_id)

    def _load_row(self, row_id: str | None) -> None:
        if row_id is None:
            self._clear_editor()
            return
        data = repo.get_row(self.table, row_id)
        if data is None:
            self._clear_editor()
            return
        self._loading = True
        self._current_id = row_id
        for field in self.spec["fields"]:
            set_editor_value(self._editors[field.key], data.get(field.key, ""))
        if self._check:
            self._check.setChecked(bool(data.get(self.spec["extra_check"][0])))
        self._loading = False
        self._clear_dirty()

    def _clear_editor(self) -> None:
        """Reset the form to a blank new entry.

        The editors stay enabled. They used to be disabled whenever no row was
        selected, which meant a freshly installed program -- empty database,
        nothing to select -- had six input boxes that showed their placeholder
        text and silently swallowed every keystroke.
        """
        self._loading = True
        self._current_id = None
        for field in self.spec["fields"]:
            if field.kind == "date":
                value = repo.today()
            elif field.key in ("source", "tags"):
                # Carry the source and tags over from the last save. Entries
                # tend to come in runs from one article with one set of tags,
                # so repeating them by hand every time is the tedious part.
                value = db.get_meta(self._carry_key(field.key), "")
            else:
                value = ""
            set_editor_value(self._editors[field.key], value)
        if self._check:
            self._check.setChecked(False)
        self._loading = False
        self._clear_dirty()

    def _carry_key(self, field_key: str) -> str:
        return f"carry_{field_key}_{self.table}"

    # -- actions ---------------------------------------------------------
    def new_entry(self) -> None:
        if self._dirty:
            self.save_current(silent=True)
        self._clear_editor()
        self.view.clearSelection()
        # Also drop the *current* index, not just the selection. Leaving it
        # behind means clicking that very row emits no currentRowChanged, so
        # the half-typed new entry would never get flushed and would be lost.
        self.view.selectionModel().clearCurrentIndex()
        self._focus_first_editor()

    def save_current(self, silent: bool = False) -> None:
        values = {f.key: editor_value(self._editors[f.key]) for f in self.spec["fields"]}
        if self._check:
            values[self.spec["extra_check"][0]] = 1 if self._check.isChecked() else 0

        required = "title" if self.table == "grammar" else "english"
        if not values.get(required) and not values.get("korean") and not values.get("body"):
            if not silent:
                QMessageBox.information(self, t("nothing_to_save"),
                                        t("nothing_to_save_body"))
            return

        self._current_id = repo.save_row(self.table, values, row_id=self._current_id)
        # Remember source and tags so the next new entry starts pre-filled with
        # them. Clearing a field and saving is respected -- it carries the
        # blank forward, which is how you signal you have moved on.
        for key in ("source", "tags"):
            if key in values:
                db.set_meta(self._carry_key(key), values[key])
        self._clear_dirty()
        self.reload()
        self.dataChanged.emit()
        if not silent:
            self._update_status(t("saved"))
            # Every explicit save drops back into a blank form, so a run of
            # entries can be typed without reaching for ＋ 새로 추가 each time.
            self.new_entry()

    def delete_selected(self) -> None:
        rows = {i.row() for i in self.view.selectionModel().selectedRows()}
        ids = [rid for rid in (self.model.row_id(r) for r in rows) if rid]
        if not ids:
            return
        answer = QMessageBox.question(
            self, t("delete_confirm"), t("delete_body", n=len(ids)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        repo.soft_delete(self.table, ids)
        if self._current_id in ids:
            self._current_id = None
        self.reload()
        self.dataChanged.emit()

    def speak_current(self) -> None:
        """Read the English out loud. Grammar notes speak their examples."""
        key = "examples" if self.table == "grammar" else "english"
        widget = self._editors.get(key)
        if widget is not None:
            tts.speak(editor_value(widget))

    def flush(self) -> None:
        """Persist pending edits -- called before the window closes."""
        if self._dirty:
            self.save_current(silent=True)


