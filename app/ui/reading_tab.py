"""2. 영어 원문 해석 해보기.

Paste a passage, it is split into one row per sentence, and each row gets a
translation cell and a self-feedback note cell.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import news, repo, theme, tts
from ..i18n import t
from .common import ArrowTextEdit, Card, ElidingLabel, english_font, hint_label
from .news_import import NewsDisclaimerDialog, NewsImportDialog

COL_NO, COL_EN, COL_TRANS, COL_NOTE = range(4)

def _length_label(sentences: int) -> str:
    # The same thresholds the fetch dialog filters by.
    return t("len_" + news.length_category_by_count(sentences))


class WrapTextDelegate(QStyledItemDelegate):
    """Wraps long cell text and, crucially, reports the height it truly needs.

    resizeRowsToContents relies on the delegate's sizeHint. The default one --
    and a plain QFontMetrics.boundingRect -- under-measure wrapped text by
    close to a line, so the last line was cut and shown as "…". QTextDocument
    lays the text out exactly as it is painted, so the height is right and the
    sentence is shown whole. Used for every text column, editable or not; the
    editor half only matters where the user types.
    """

    def sizeHint(self, option, index):
        text = str(index.data(Qt.DisplayRole) or "")
        width = option.rect.width()
        if width <= 0:                       # columns not laid out yet
            width = 160
        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setTextWidth(max(40, width - 12))
        document.setPlainText(text)
        return QSize(width, int(document.size().height()) + 12)

    def createEditor(self, parent, option, index):
        # ArrowTextEdit so "->" becomes "→" here too -- this is where the user
        # hand-types a translation, the same as the entry tabs.
        editor = ArrowTextEdit(parent)
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
        left, right = self._build_left(), self._build_right()
        # Modest, explicit minimums. Without them each panel's minimum is
        # driven by its content -- a long article headline blew the right
        # panel's minimum up past 800px, so the splitter could not shrink it
        # and it overlapped the left. These sum well under any window, so the
        # handle always has somewhere to go and the panels never collide.
        left.setMinimumWidth(180)
        right.setMinimumWidth(460)     # fits the button bar without clipping
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
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
        # Long article titles elide instead of demanding a horizontal
        # scrollbar and a wider panel.
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setWordWrap(False)
        # Ctrl/Shift-click to select several passages and delete them at once,
        # the same as the tables in the other tabs.
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.currentItemChanged.connect(self._on_passage_selected)
        delete_key = QShortcut(QKeySequence.Delete, self.list)
        delete_key.setContext(Qt.WidgetShortcut)
        delete_key.activated.connect(self.delete_passage)
        layout.addWidget(self.list, 1)

        # Fetch recent articles -- a shortcut to finding English to translate,
        # above the manual "paste your own" button.
        self.fetch_btn = QPushButton()
        self.fetch_btn.clicked.connect(self.fetch_news)
        layout.addWidget(self.fetch_btn)

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
        # Eliding, not plain: a fetched article's headline is long, and a
        # plain label would force the whole panel as wide as the text.
        self.title_label = ElidingLabel()
        self.title_label.setObjectName("title")
        head.addWidget(self.title_label, 1)

        # Attribution for a fetched passage: a link back to the original.
        # Hidden for passages the user pasted themselves.
        self.source_link = QLabel()
        self.source_link.setObjectName("hint")
        self.source_link.setOpenExternalLinks(True)
        self.source_link.setVisible(False)
        head.addWidget(self.source_link)

        self.progress_label = hint_label()
        head.addWidget(self.progress_label)
        layout.addWidget(self.head)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        # Parent given at construction -- see the note in entry_tab.py: a
        # parentless widget made visible becomes its own top-level window.
        self.speak_btn = QPushButton("🔊", self.right_card)
        self.speak_btn.setObjectName("speak")
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
        # Never elide: a sentence must be shown in full. With eliding on, a
        # long sentence in the stretch English column was cut to "...the two
        # powerful earthquakes that shook Venezuela o…" whenever the row was
        # not tall enough. Off, it wraps; the row height is what has to keep
        # up, which _refit_rows below ensures.
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.SolidLine)
        self.table.setFrameShape(QTableWidget.NoFrame)
        # Every text column gets the wrapping delegate, the English one too --
        # it holds the longest text and was the one being cut.
        self.table.setItemDelegateForColumn(COL_EN, WrapTextDelegate(self))
        self.table.setItemDelegateForColumn(COL_TRANS, WrapTextDelegate(self))
        self.table.setItemDelegateForColumn(COL_NOTE, WrapTextDelegate(self))
        self.table.itemChanged.connect(self._on_cell_changed)
        # Right-click a row (or a run of adjacent rows) to merge or delete
        # sentences the splitter got wrong.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(COL_NO, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_EN, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_TRANS, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_NO, 40)
        self.table.setColumnWidth(COL_NOTE, 210)

        # Row heights are computed from the wrapped text, which depends on the
        # column width -- and stretch columns only get their real width after
        # the table is laid out. Re-fitting once the columns settle stops long
        # sentences from clipping.
        #
        # Debounced, and this matters: resizeRowsToContents lays out every
        # cell (a QTextDocument each), so running it on every frame of a
        # splitter drag -- which resizes the stretch columns continuously --
        # made dragging lag badly. A single-shot timer that each resize
        # *restarts* runs it once, ~120ms after the drag settles, not during.
        self._refit = QTimer(self)
        self._refit.setSingleShot(True)
        self._refit.setInterval(120)
        self._refit.timeout.connect(self.table.resizeRowsToContents)
        header.sectionResized.connect(lambda *_: self._refit.start())

        layout.addWidget(self.table, 1)

        self.hint = hint_label()
        layout.addWidget(self.hint)
        return self.right_card

    # -- theming / language ----------------------------------------------
    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        self.left_card.restyle(p)
        self.right_card.restyle(p)
        # reload() repaints the passage list too -- its "completed" entries
        # carry the success colour of whatever palette painted them last.
        self.reload()
        if self._passage_id:
            self._show_lines(repo.passage_lines(self._passage_id))

    def retranslate(self) -> None:
        self.search.setPlaceholderText(t("passage_search"))
        self.fetch_btn.setText(t("fetch_news"))
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
                f"{row['title']}\n{_length_label(total)} · "
                f"{t('progress_short', done=done, total=total)}")
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
        # The stored URL is data -- it may have arrived through a merge from
        # another device -- and it goes into rich text that opens external
        # links. Only http(s) is linkified, and the value is escaped so it
        # cannot inject markup into the label.
        url = (passage or {}).get("source_url", "")
        if url and url.lower().startswith(("http://", "https://")):
            self.source_link.setText(
                f'<a href="{html.escape(url, quote=True)}">'
                f'{t("news_open_original")}</a>')
        else:
            url = ""
        self.source_link.setVisible(bool(url))
        self.head.setVisible(True)
        self._show_lines(repo.passage_lines(self._passage_id))

    def _show_lines(self, lines: list[dict]) -> None:
        self._loading = True
        self.table.clearSpans()          # headings from a previous passage
        self.table.setRowCount(0)
        self._line_ids = []

        p = self.palette
        pending = QColor(p.accents[3] if p.accents else p.surface_alt)
        font = english_font(10)

        self.table.setRowCount(len(lines))
        done = 0
        total = 0            # sentences only; a heading is not one to translate
        for row, line in enumerate(lines):
            self._line_ids.append(line["id"])

            if news.is_heading(line["english"]):
                # A section heading: bold, spanning the sentence columns, with
                # no number and no translation cell -- it is a signpost, not a
                # row to work on.
                self.table.setSpan(row, COL_EN, 1, 3)
                head_item = QTableWidgetItem(news.heading_text(line["english"]))
                head_item.setFlags(Qt.ItemIsEnabled)
                heading_font = QFont(font)
                heading_font.setBold(True)
                heading_font.setPointSize(font.pointSize() + 1)
                head_item.setFont(heading_font)
                head_item.setForeground(QColor(p.primary))
                head_item.setBackground(QColor(p.surface_alt))
                self.table.setItem(row, COL_EN, head_item)
                blank = QTableWidgetItem("")
                blank.setFlags(Qt.ItemIsEnabled)
                blank.setBackground(QColor(p.surface_alt))
                self.table.setItem(row, COL_NO, blank)
                continue

            total += 1
            no_item = QTableWidgetItem(str(total))
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
        # ...and again once the stretch columns have their real width, or the
        # first pass (computed at a stale width) leaves long sentences clipped.
        self._refit.start()
        self._loading = False
        # `total` counted sentences only, so headings do not inflate progress.
        # The length badge sits before it: e.g. "김 · 52문장  0 / 52 문장 해석함".
        if total:
            self.progress_label.setText(
                f"{_length_label(total)}  ·  "
                f"{t('progress_done', done=done, total=total)}")
        else:
            self.progress_label.setText("")

    # -- merge / delete sentences ----------------------------------------
    def _selected_line_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()}
                      or {i.row() for i in self.table.selectedIndexes()})

    def _row_menu(self, pos) -> None:
        if not self._passage_id:
            return
        rows = self._selected_line_rows()
        clicked = self.table.rowAt(pos.y())
        if clicked >= 0 and clicked not in rows:
            rows = [clicked]
            self.table.selectRow(clicked)
        if not rows:
            return

        menu = QMenu(self)
        # Merge: two or more rows that are adjacent (no gap). Non-adjacent
        # selections cannot merge -- the joined text would jump the passage.
        adjacent = len(rows) >= 2 and rows == list(range(rows[0], rows[0] + len(rows)))
        merge = menu.addAction(t("merge_sentences"))
        merge.setEnabled(adjacent)
        if len(rows) >= 2 and not adjacent:
            merge.setText(t("merge_need_adjacent"))
        delete = menu.addAction(t("delete_sentence"))
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))

        if chosen is merge and adjacent:
            self._merge_rows(rows)
        elif chosen is delete:
            self._delete_rows(rows)

    def _merge_rows(self, rows: list[int]) -> None:
        ids = [self._line_ids[r] for r in rows if r < len(self._line_ids)]
        if len(ids) < 2:
            return
        survivor = repo.merge_passage_lines(ids)
        self._reload_lines()
        if survivor:                    # keep the merged row selected
            for i, lid in enumerate(self._line_ids):
                if lid == survivor:
                    self.table.selectRow(i)
                    break
        self.dataChanged.emit()

    def _delete_rows(self, rows: list[int]) -> None:
        ids = [self._line_ids[r] for r in rows if r < len(self._line_ids)]
        if not ids:
            return
        if len(ids) == 1:
            body = t("delete_sentence_body")
        else:
            body = t("delete_sentences_n_body", n=len(ids))
        if QMessageBox.question(self, t("delete_sentence"), body,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        repo.delete_passage_lines(ids)
        self._reload_lines()
        self.dataChanged.emit()

    def _reload_lines(self) -> None:
        if self._passage_id:
            self._show_lines(repo.passage_lines(self._passage_id))

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
    def fetch_news(self) -> None:
        # The disclaimer, once. It states plainly that this is for personal
        # study, that copyright must be respected, and that the user carries
        # any legal responsibility -- and it is not passable without agreeing.
        if not NewsDisclaimerDialog.already_agreed():
            gate = NewsDisclaimerDialog(self)
            agreed = gate.exec() == QDialog.Accepted
            gate.deleteLater()
            if not agreed:
                return

        dialog = NewsImportDialog(self)
        accepted = dialog.exec() == QDialog.Accepted
        created = dialog.created
        dialog.deleteLater()
        if accepted and created:
            self.reload()
            self.dataChanged.emit()
            QMessageBox.information(self, t("fetch_news_title"),
                                    t("news_done", n=created))

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
        # Every selected passage, not just the current one. Falls back to the
        # current passage when nothing is multi-selected.
        ids = [self.list.item(i).data(Qt.UserRole)
               for i in range(self.list.count())
               if self.list.item(i).isSelected()]
        if not ids and self._passage_id:
            ids = [self._passage_id]
        if not ids:
            return

        if len(ids) == 1:
            passage = repo.get_row("passages", ids[0])
            body = t("delete_passage_body",
                     title=passage["title"] if passage else "")
        else:
            body = t("delete_passages_body", n=len(ids))
        answer = QMessageBox.question(
            self, t("delete_passage"), body,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        repo.soft_delete("passages", ids)      # cascades to each passage's lines
        if self._passage_id in ids:
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
        repo.save_row("passages", {"title": title or t("untitled"), "tags": tags},
                      row_id=self._passage_id)
        repo.resplit_passage(self._passage_id, text)
        self.reload()
        self.dataChanged.emit()

    def _send_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, t("no_selection"), t("no_selection_body"))
            return
        sent = 0
        for row in rows:
            english = (self.table.item(row, COL_EN) or QTableWidgetItem()).text()
            korean = (self.table.item(row, COL_TRANS) or QTableWidgetItem()).text()
            english = news.heading_text(english)   # drop any "## " from a heading
            if english.strip():
                self.sendToSentences.emit(english, korean)
                sent += 1
        # Count what was actually sent -- rows with no English are skipped.
        QMessageBox.information(self, t("added"), t("added_body", n=sent))

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


