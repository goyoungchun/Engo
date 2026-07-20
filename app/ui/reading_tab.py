"""2. 영어 원문 해석 해보기.

Paste a passage, it is split into one row per sentence, and each row gets a
translation cell and a self-feedback note cell.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import repo, theme, tts
from ..i18n import t
from .common import Card, english_font, hint_label

COL_NO, COL_EN, COL_TRANS, COL_NOTE = range(4)


class WrapTextDelegate(QStyledItemDelegate):
    """Cell editor that accepts newlines -- a translation often needs them."""

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setTabChangesFocus(True)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText().strip(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        rect = option.rect
        rect.setHeight(max(rect.height(), 72))
        editor.setGeometry(rect)


class NewPassageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("new_passage_title"))
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        layout.addWidget(QLabel(t("f_title")))
        self.title = QLineEdit()
        self.title.setPlaceholderText(t("ph_passage_title"))
        layout.addWidget(self.title)

        layout.addWidget(QLabel(t("f_tags_optional")))
        self.tags = QLineEdit()
        layout.addWidget(self.tags)

        layout.addWidget(QLabel(t("paste_here")))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(t("ph_paste"))
        layout.addWidget(self.text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText(t("split_button"))
        ok.setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText(t("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str]:
        return self.title.text().strip(), self.text.toPlainText(), self.tags.text().strip()


class ReadingTab(QWidget):
    dataChanged = Signal()
    sendToSentences = Signal(str, str)   # english, korean

    def __init__(self, palette: theme.Palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self._passage_id: str | None = None
        self._line_ids: list[str] = []
        self._loading = False
        self._build()
        self.restyle(palette)
        self.retranslate()
        self.reload()

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(14)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 820])
        outer.addWidget(splitter, 1)

    def _build_left(self) -> QWidget:
        self.left_card = Card(padding=14)
        layout = self.left_card.body

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setFrameShape(QListWidget.NoFrame)
        self.list.currentItemChanged.connect(self._on_passage_selected)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.add_btn = QPushButton()
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.new_passage)
        row.addWidget(self.add_btn)

        self.del_btn = QPushButton()
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.delete_passage)
        row.addWidget(self.del_btn)
        layout.addLayout(row)
        return self.left_card

    def _build_right(self) -> QWidget:
        self.right_card = Card(padding=16)
        layout = self.right_card.body

        # A widget rather than a bare layout: an empty layout row still takes
        # up its height, which left a blank strip once the placeholder text
        # was removed. Hiding a widget collapses the space properly.
        self.head = QWidget()
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        head.addWidget(self.title_label, 1)

        self.progress_label = hint_label()
        head.addWidget(self.progress_label)
        layout.addWidget(self.head)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        # Parent given at construction -- see the note in entry_tab.py: a
        # parentless widget made visible becomes its own top-level window.
        self.speak_btn = QPushButton("🔊", self.right_card)
        self.speak_btn.setFixedWidth(46)
        self.speak_btn.clicked.connect(self._speak_selected)
        self.speak_btn.setVisible(tts.installed())
        bar.addWidget(self.speak_btn)

        self.send_btn = QPushButton()
        self.send_btn.clicked.connect(self._send_selected)
        bar.addWidget(self.send_btn)

        self.resplit_btn = QPushButton()
        self.resplit_btn.clicked.connect(self._resplit)
        bar.addWidget(self.resplit_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.SolidLine)
        self.table.setFrameShape(QTableWidget.NoFrame)
        self.table.setItemDelegateForColumn(COL_TRANS, WrapTextDelegate(self))
        self.table.setItemDelegateForColumn(COL_NOTE, WrapTextDelegate(self))
        self.table.itemChanged.connect(self._on_cell_changed)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(COL_NO, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_EN, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_TRANS, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_NO, 40)
        self.table.setColumnWidth(COL_NOTE, 210)
        layout.addWidget(self.table, 1)

        self.hint = hint_label()
        layout.addWidget(self.hint)
        return self.right_card

    # -- theming / language ----------------------------------------------
    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        self.left_card.restyle(p)
        self.right_card.restyle(p)
        if self._passage_id:
            self._show_lines(repo.passage_lines(self._passage_id))

    def retranslate(self) -> None:
        self.search.setPlaceholderText(t("passage_search"))
        self.add_btn.setText(t("new_passage"))
        self.del_btn.setText(t("delete"))
        self.speak_btn.setToolTip(t("speak_tip"))
        self.send_btn.setText(t("send_to_sentences"))
        self.send_btn.setToolTip(t("send_tip"))
        self.resplit_btn.setText(t("resplit"))
        self.resplit_btn.setToolTip(t("resplit_tip"))
        self.hint.setText(t("reading_hint"))
        self.table.setHorizontalHeaderLabels(
            [t("col_no"), t("col_source_en"), t("col_my_translation"), t("col_feedback")])
        for col in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                # The number column is centred over its centred values; the
                # text columns start where their text starts.
                item.setTextAlignment(Qt.AlignCenter if col == COL_NO
                                      else Qt.AlignLeft | Qt.AlignVCenter)
        self.reload()

    # -- passage list ----------------------------------------------------
    def reload(self) -> None:
        keep = self._passage_id
        self.list.blockSignals(True)
        self.list.clear()
        for row in repo.list_rows("passages", search=self.search.text(), limit=500):
            done, total = row.get("done_count", 0), row.get("line_count", 0)
            item = QListWidgetItem(
                f"{row['title']}\n{t('progress_short', done=done, total=total)}")
            item.setData(Qt.UserRole, row["id"])
            if total and done >= total:
                item.setForeground(QColor(self.palette.success))
            self.list.addItem(item)
        self.list.blockSignals(False)

        if keep:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole) == keep:
                    self.list.setCurrentRow(i)
                    return
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._passage_id = None
            self._show_lines([])
            self.title_label.setText("")
            self.progress_label.setText("")
            self.head.setVisible(False)

    def _on_passage_selected(self, current, _previous) -> None:
        if current is None:
            return
        self._passage_id = current.data(Qt.UserRole)
        passage = repo.get_row("passages", self._passage_id)
        if passage:
            self.title_label.setText(passage["title"])
        self.head.setVisible(True)
        self._show_lines(repo.passage_lines(self._passage_id))

    def _show_lines(self, lines: list[dict]) -> None:
        self._loading = True
        self.table.setRowCount(0)
        self._line_ids = []

        p = self.palette
        pending = QColor(p.accents[3] if p.accents else p.surface_alt)
        font = english_font(10)

        self.table.setRowCount(len(lines))
        done = 0
        for row, line in enumerate(lines):
            self._line_ids.append(line["id"])

            no_item = QTableWidgetItem(str(row + 1))
            no_item.setFlags(Qt.ItemIsEnabled)
            no_item.setTextAlignment(Qt.AlignCenter)
            no_item.setForeground(QColor(p.text_faint))
            self.table.setItem(row, COL_NO, no_item)

            en_item = QTableWidgetItem(line["english"])
            en_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            en_item.setFont(font)
            self.table.setItem(row, COL_EN, en_item)

            trans_item = QTableWidgetItem(line["translation"])
            if line["translation"].strip():
                done += 1
            else:
                trans_item.setBackground(pending)
            self.table.setItem(row, COL_TRANS, trans_item)

            note_item = QTableWidgetItem(line["note"])
            note_item.setForeground(QColor(p.text_muted))
            self.table.setItem(row, COL_NOTE, note_item)

        self.table.resizeRowsToContents()
        self._loading = False
        total = len(lines)
        self.progress_label.setText(
            t("progress_done", done=done, total=total) if total else "")

    # -- editing ---------------------------------------------------------
    def _on_cell_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() not in (COL_TRANS, COL_NOTE):
            return
        row = item.row()
        if row >= len(self._line_ids):
            return
        key = "translation" if item.column() == COL_TRANS else "note"
        repo.save_row("passage_lines", {key: item.text()}, row_id=self._line_ids[row])

        if item.column() == COL_TRANS:
            p = self.palette
            item.setBackground(QColor(p.surface) if item.text().strip()
                               else QColor(p.accents[3] if p.accents else p.surface_alt))
            self._refresh_progress()
        self.table.resizeRowToContents(row)
        self.dataChanged.emit()

    def _refresh_progress(self) -> None:
        total = len(self._line_ids)
        done = sum(
            1 for r in range(total)
            if (self.table.item(r, COL_TRANS) or QTableWidgetItem()).text().strip()
        )
        self.progress_label.setText(
            t("progress_done", done=done, total=total) if total else "")
        item = self.list.currentItem()
        if item:
            title = item.text().split("\n")[0]
            self.list.blockSignals(True)
            item.setText(f"{title}\n{t('progress_short', done=done, total=total)}")
            self.list.blockSignals(False)

    # -- actions ---------------------------------------------------------
    def new_passage(self) -> None:
        dialog = NewPassageDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        title, text, tags = dialog.values()
        if not text.strip():
            QMessageBox.information(self, t("no_text"), t("no_text_body"))
            return
        self._passage_id = repo.create_passage(title or t("untitled"), text, tags)
        self.reload()
        self.dataChanged.emit()

    def delete_passage(self) -> None:
        if not self._passage_id:
            return
        passage = repo.get_row("passages", self._passage_id)
        answer = QMessageBox.question(
            self, t("delete_passage"),
            t("delete_passage_body", title=passage["title"] if passage else ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        repo.soft_delete("passages", [self._passage_id])
        self._passage_id = None
        self.reload()
        self.dataChanged.emit()

    def _resplit(self) -> None:
        if not self._passage_id:
            return
        passage = repo.get_row("passages", self._passage_id)
        if not passage:
            return
        dialog = NewPassageDialog(self)
        dialog.setWindowTitle(t("resplit"))
        dialog.title.setText(passage["title"])
        dialog.tags.setText(passage["tags"])
        dialog.text.setPlainText(passage["raw_text"])
        if dialog.exec() != QDialog.Accepted:
            return
        title, text, tags = dialog.values()
        repo.save_row("passages", {"title": title, "tags": tags},
                      row_id=self._passage_id)
        repo.resplit_passage(self._passage_id, text)
        self.reload()
        self.dataChanged.emit()

    def _send_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, t("no_selection"), t("no_selection_body"))
            return
        for row in rows:
            english = (self.table.item(row, COL_EN) or QTableWidgetItem()).text()
            korean = (self.table.item(row, COL_TRANS) or QTableWidgetItem()).text()
            if english.strip():
                self.sendToSentences.emit(english, korean)
        QMessageBox.information(self, t("added"), t("added_body", n=len(rows)))

    def _speak_selected(self) -> None:
        """Read the chosen sentences; with nothing chosen, read the passage."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            rows = range(self.table.rowCount())
        parts = [(self.table.item(r, COL_EN) or QTableWidgetItem()).text()
                 for r in rows]
        tts.speak(" ".join(p for p in parts if p.strip()))

    def flush(self) -> None:
        if self.table.state() == QAbstractItemView.EditingState:
            self.table.closePersistentEditor(self.table.currentItem())

