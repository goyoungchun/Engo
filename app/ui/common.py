"""Shared UI pieces: the lazy table model, form field specs, small widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QVBoxLayout, QWidget,
)

from .. import i18n, repo, theme
from ..i18n import t


@dataclass
class Column:
    key: str
    title_key: str
    width: int = 160
    stretch: bool = False
    centred: bool = False


# Column key for "which row is this" -- the value is the position in the list,
# so it comes from the model rather than from the database.
ROW_NUMBER = "rownum"


@dataclass
class Field:
    key: str
    label_key: str
    kind: str = "line"        # line | text | date
    height: int = 0
    placeholder_key: str = ""


class Card(QFrame):
    """White rounded panel -- the basic surface of the design."""

    def __init__(self, parent=None, padding: int = 16):
        super().__init__(parent)
        self.setObjectName("card")
        p = theme.PALETTES[theme.DEFAULT_PALETTE]
        self.setStyleSheet("")     # colours come from restyle()
        self._padding = padding
        layout = QVBoxLayout(self)
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(10)
        self.body = layout

    def restyle(self, p: theme.Palette) -> None:
        self.setStyleSheet(
            f"QFrame#card {{ background: {p.surface};"
            f" border: 1px solid {p.border};"
            f" border-radius: {theme.RADIUS_CARD}px; }}"
        )


class Pill(QLabel):
    """Small rounded tag chip in one of the palette's pastel tints."""

    def __init__(self, text: str, index: int, p: theme.Palette, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.restyle(index, p)

    def restyle(self, index: int, p: theme.Palette) -> None:
        if not p.accents:
            return
        i = index % len(p.accents)
        self.setStyleSheet(
            f"background: {p.accents[i]}; color: {p.accent_text};"
            f" border: 1px solid {p.accent_borders[i]};"
            f" border-radius: 9px; padding: 2px 9px; font-size: 8pt;"
        )


class LazyTableModel(QAbstractTableModel):
    """Table model that pulls rows a page at a time.

    Qt's canFetchMore/fetchMore protocol means a 5,000-row table costs the
    same at startup as a 50-row one: only what is scrolled into view is ever
    read out of SQLite, and the query already truncates long note text (see
    repo.LIST_COLUMNS).
    """

    PAGE = 200

    def __init__(self, table: str, columns: list[Column], parent=None):
        super().__init__(parent)
        self.table = table
        self.columns = columns
        self.palette = theme.PALETTES[theme.DEFAULT_PALETTE]
        self._rows: list[dict[str, Any]] = []
        self._total = 0
        self._filters: dict[str, str] = {}

    # -- data ------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = self.columns[index.column()]

        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            if col.key == ROW_NUMBER:
                return str(index.row() + 1)
            value = row.get(col.key, "")
            if col.key == "box":
                return i18n.box_label(value)
            if col.key == "starred":
                return "★" if value else ""
            text = str(value or "")
            if role == Qt.DisplayRole:
                # Newlines would make the row height jump; the tooltip keeps them.
                return text.replace("\n", " ⏎ ")
            return text

        if role == Qt.TextAlignmentRole and col.centred:
            return int(Qt.AlignCenter)

        if role == Qt.ForegroundRole:
            if col.key in ("korean", "body", ROW_NUMBER):
                return QColor(self.palette.text_muted)
            if col.key == "starred":
                return QColor(self.palette.primary)

        if role == Qt.FontRole and col.key in ("english", "title"):
            font = QFont()
            font.setWeight(QFont.DemiBold)
            return font

        return None

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return section + 1 if role == Qt.DisplayRole else None
        column = self.columns[section]
        if role == Qt.DisplayRole:
            return t(column.title_key) if column.title_key else ""
        if role == Qt.TextAlignmentRole:
            # Headings sit above the start of their column, except for narrow
            # centred columns where centring the heading reads better.
            return int(Qt.AlignCenter if column.centred
                       else Qt.AlignLeft | Qt.AlignVCenter)
        return None

    # -- paging ----------------------------------------------------------
    def canFetchMore(self, parent=QModelIndex()) -> bool:
        return not parent.isValid() and len(self._rows) < self._total

    def fetchMore(self, parent=QModelIndex()) -> None:
        if parent.isValid():
            return
        more = repo.list_rows(self.table, limit=self.PAGE,
                              offset=len(self._rows), **self._filters)
        if not more:
            self._total = len(self._rows)
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(more) - 1)
        self._rows.extend(more)
        self.endInsertRows()

    def refresh(self, **filters) -> None:
        if filters:
            self._filters = filters
        self.beginResetModel()
        self._total = repo.count_rows(self.table, **self._filters)
        self._rows = repo.list_rows(self.table, limit=self.PAGE, offset=0,
                                    **self._filters)
        self.endResetModel()

    def restyle(self, p: theme.Palette) -> None:
        self.palette = p
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1,
                                             len(self.columns) - 1))
        self.headerDataChanged.emit(Qt.Horizontal, 0, len(self.columns) - 1)

    # -- helpers ---------------------------------------------------------
    def row_id(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]["id"]
        return None

    def index_of(self, row_id: str) -> int:
        for i, r in enumerate(self._rows):
            if r["id"] == row_id:
                return i
        return -1

    @property
    def total(self) -> int:
        return self._total


def make_editor(field: Field) -> QWidget:
    if field.kind == "text":
        w = QPlainTextEdit()
        if field.height:
            w.setFixedHeight(field.height)
        w.setTabChangesFocus(True)
        return w
    if field.kind == "date":
        w = QDateEdit()
        w.setCalendarPopup(True)
        w.setDisplayFormat("yyyy-MM-dd")
        return w
    return QLineEdit()


def apply_placeholder(widget: QWidget, field: Field) -> None:
    """Placeholders are re-applied on language change, so they live here."""
    if not field.placeholder_key:
        return
    if isinstance(widget, (QPlainTextEdit, QLineEdit)):
        widget.setPlaceholderText(t(field.placeholder_key))


def editor_value(widget: QWidget) -> Any:
    if isinstance(widget, QPlainTextEdit):
        return widget.toPlainText().strip()
    if isinstance(widget, QDateEdit):
        return widget.date().toString("yyyy-MM-dd")
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    return ""


def set_editor_value(widget: QWidget, value: Any) -> None:
    from PySide6.QtCore import QDate
    if isinstance(widget, QPlainTextEdit):
        widget.setPlainText(str(value or ""))
    elif isinstance(widget, QDateEdit):
        text = str(value or "") or repo.today()
        date = QDate.fromString(text, "yyyy-MM-dd")
        widget.setDate(date if date.isValid() else QDate.currentDate())
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value or ""))


def english_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont(theme.ENGLISH_FONT)
    font.setPointSize(size)
    font.setBold(bold)
    return font


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("section")
    return label


def hint_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    return label


def toolbar_row() -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    return row


def scrollable(inner: QWidget) -> QWidget:
    """Wrap a panel so it scrolls instead of squashing its children.

    Without this, a form taller than the window does not shrink -- the fields
    have fixed heights, so Qt lays them out on top of each other and the text
    boxes visibly overlap. Scrolling is the honest answer to "not enough room".
    """
    from PySide6.QtWidgets import QScrollArea

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(inner)

    # Deliberately NOT a stylesheet. Both `QWidget { background: transparent }`
    # and a bare `background: transparent;` set on the area or its viewport
    # cascade to every descendant, and an ancestor's stylesheet outranks the
    # application one -- which silently stripped the violet fill off the
    # primary buttons. Turning off background filling has no such reach.
    area.viewport().setAutoFillBackground(False)
    inner.setAutoFillBackground(False)
    return area


def round_menu(menu) -> None:
    """Let a popup menu's rounded corners actually be round.

    The stylesheet draws the menu panel with a border-radius, but the popup is
    a real top-level window and it is opaque and square, so the area outside
    the curve stayed filled -- reading as a square outline around the rounded
    panel. Making the window translucent and frameless lets the corners cut.
    """
    menu.setAttribute(Qt.WA_TranslucentBackground)
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint
                        | Qt.NoDropShadowWindowHint)
    return menu


def round_corners(widget) -> None:
    """Ask Windows 11 to round this window's corners.

    The client area is drawn with rounded cards inside, so square window
    corners read as a mismatch. Silently does nothing on older Windows.
    """
    import ctypes
    from ctypes import wintypes

    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    try:
        value = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(int(widget.winId())),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError, ValueError):
        pass
