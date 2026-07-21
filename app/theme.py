"""Design tokens and stylesheet generation.

The look follows a task-manager style: a tinted page background, white cards
with generous corner radius, one saturated accent colour for anything
actionable, and a set of pastel tints for category chips and sticky notes.

Everything the UI paints comes from a Palette, so switching colour scheme is a
matter of swapping one object and re-applying the stylesheet -- no widget
needs to know which theme is active.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Palette:
    key: str
    name_ko: str
    name_en: str

    primary: str            # buttons, selected tabs, focus rings
    primary_hover: str
    primary_press: str
    primary_text: str       # text drawn on top of `primary`
    primary_soft: str       # tinted fill for selections and chips

    bg: str                 # window background
    surface: str            # cards, inputs, tables
    surface_alt: str        # table headers, secondary strips
    border: str
    border_strong: str

    text: str
    text_muted: str
    text_faint: str

    danger: str
    danger_soft: str
    success: str

    # Pastel tints, used for tag chips and sticky notes.
    accents: tuple[str, ...] = ()
    accent_borders: tuple[str, ...] = ()
    accent_text: str = "#2B2B45"

    dark: bool = False


VIOLET = Palette(
    key="violet", name_ko="바이올렛", name_en="Violet",
    primary="#6C5CE7", primary_hover="#5B4BD6", primary_press="#4E3FC4",
    primary_text="#FFFFFF", primary_soft="#EAE6FD",
    bg="#F5F4FD", surface="#FFFFFF", surface_alt="#F7F6FE",
    border="#E8E5F6", border_strong="#D5D0EE",
    text="#1E1E32", text_muted="#7B7B98", text_faint="#A9A9C0",
    danger="#E5544B", danger_soft="#FDECEA", success="#2FA36B",
    accents=("#E7E0FE", "#D8F5E4", "#FFE6D4", "#FFF2CE", "#FFDEE9", "#DBE8FF"),
    accent_borders=("#CFC2FB", "#B6E7CC", "#FFCFAE", "#FFE4A3", "#FFC4D8", "#BBD3FA"),
)

OCEAN = Palette(
    key="ocean", name_ko="오션", name_en="Ocean",
    primary="#2E7DF7", primary_hover="#2569D6", primary_press="#1F58B8",
    primary_text="#FFFFFF", primary_soft="#E2EDFE",
    bg="#F3F7FD", surface="#FFFFFF", surface_alt="#F5F9FE",
    border="#E1EAF5", border_strong="#C9D9EC",
    text="#12233A", text_muted="#657B94", text_faint="#9BAABC",
    danger="#E5544B", danger_soft="#FDECEA", success="#2FA36B",
    accents=("#DBE8FF", "#D3F1F5", "#DFF3E0", "#FFF1D2", "#FFE1E6", "#E6E2FB"),
    accent_borders=("#B8D2FA", "#ACE0E8", "#BEE4C0", "#FFE0A6", "#FFC3CD", "#CCC5F5"),
)

FOREST = Palette(
    key="forest", name_ko="포레스트", name_en="Forest",
    primary="#2E9E6B", primary_hover="#268759", primary_press="#1F704A",
    primary_text="#FFFFFF", primary_soft="#DFF3E9",
    bg="#F3FAF6", surface="#FFFFFF", surface_alt="#F5FBF8",
    border="#DFEDE5", border_strong="#C3DED0",
    text="#14291F", text_muted="#63806F", text_faint="#9AB0A4",
    danger="#D9534F", danger_soft="#FBEBEA", success="#2E9E6B",
    accents=("#DFF3E0", "#DDEEDC", "#FFF0CE", "#FFE3D4", "#DEECFB", "#EDE5FA"),
    accent_borders=("#BCE1BE", "#C2DFC0", "#FFDFA1", "#FFCBAE", "#BFD9F3", "#D4C7F2"),
)

SUNSET = Palette(
    key="sunset", name_ko="선셋", name_en="Sunset",
    primary="#F0705A", primary_hover="#DC5F4A", primary_press="#C34E3B",
    primary_text="#FFFFFF", primary_soft="#FDE6E1",
    bg="#FEF6F3", surface="#FFFFFF", surface_alt="#FEF8F5",
    border="#F6E4DD", border_strong="#EFCCC1",
    text="#33201A", text_muted="#8B6E64", text_faint="#B8A098",
    danger="#D64545", danger_soft="#FBE9E9", success="#3B9E6E",
    accents=("#FFE6D4", "#FFDCDC", "#FFF2CE", "#E8E7FB", "#DCEFE4", "#DDE9FA"),
    accent_borders=("#FFC9A8", "#FFBDBD", "#FFE2A0", "#CFCCF6", "#B9DEC8", "#BAD3F5"),
)

MIDNIGHT = Palette(
    key="midnight", name_ko="미드나잇", name_en="Midnight",
    primary="#7C6CF5", primary_hover="#8E80F8", primary_press="#6B5AE8",
    primary_text="#FFFFFF", primary_soft="#2C2A47",
    bg="#15141F", surface="#1E1D2B", surface_alt="#242235",
    border="#2E2C42", border_strong="#3D3A55",
    text="#EBEAF5", text_muted="#9B99B8", text_faint="#6E6C8A",
    danger="#F0736B", danger_soft="#3A2427", success="#4FC08A",
    accents=("#332F52", "#24413A", "#43332B", "#443B24", "#432B37", "#25344F"),
    accent_borders=("#4A4477", "#356154", "#634C3E", "#645833",
                    "#63404F", "#374D73"),
    accent_text="#EBEAF5",
    dark=True,
)

PALETTES: dict[str, Palette] = {
    p.key: p for p in (VIOLET, OCEAN, FOREST, SUNSET, MIDNIGHT)
}
DEFAULT_PALETTE = "violet"


# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------

# The reference design uses a rounded geometric sans. Noto Sans KR is the
# closest thing that ships on this machine and covers Korean properly; the
# rest are fallbacks for machines without it.
UI_FONT_STACK = "'Noto Sans KR', 'Malgun Gothic', 'Segoe UI', sans-serif"
ENGLISH_FONT = "Georgia"        # study material reads better in a serif


def font_stack() -> str:
    return UI_FONT_STACK


# --------------------------------------------------------------------------
# stylesheet
# --------------------------------------------------------------------------

RADIUS_CARD = 14
RADIUS_INPUT = 10
RADIUS_PILL = 16


def build_style(p: Palette) -> str:
    """Whole-application stylesheet for one palette.

    Every rule that sets a background also sets a colour -- leaving text to
    the system palette is what makes widgets render invisibly when Windows
    reports a theme Qt did not expect.
    """
    return f"""
QWidget {{
    font-family: {UI_FONT_STACK};
    font-size: 10pt;
    color: {p.text};
}}
QMainWindow, QDialog {{ background: {p.bg}; }}

/* ---- tabs ------------------------------------------------------------ */
QTabWidget::pane {{
    border: none;
    background: {p.bg};
    top: -1px;
}}
/* Indent the tab strip so the first tab starts on the same line as the
   content below it (which has a 16px margin). */
QTabWidget::tab-bar {{ left: 16px; }}
QTabBar {{ qproperty-drawBase: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: 9px 20px;
    margin-right: 4px;
    border: none;
    border-radius: {RADIUS_PILL}px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {p.primary};
    color: {p.primary_text};
}}
QTabBar::tab:hover:!selected {{
    background: {p.primary_soft};
    color: {p.text};
}}

/* ---- cards / tables -------------------------------------------------- */
QTableView, QListWidget, QTableWidget {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_CARD}px;
    gridline-color: {p.border};
    selection-background-color: {p.primary_soft};
    selection-color: {p.text};
    /* No padding: it inset the header from the frame and left a ring of
       background visible between the two borders. */
    padding: 0;
}}
QTableView::item, QTableWidget::item {{
    padding: 6px 8px;
    border: none;
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background: {p.primary_soft};
    color: {p.text};
}}
QListWidget::item {{
    padding: 9px 8px;
    border-radius: {RADIUS_INPUT}px;
    margin: 2px 0;
}}
QListWidget::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
QListWidget::item:hover:!selected {{ background: {p.surface_alt}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text_muted};
    padding: 8px;
    border: none;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border_strong};
    font-weight: 600;
}}
/* The header band is square while the table is rounded, which left a notch of
   background showing at the two top corners. Round the end sections to match. */
QHeaderView::section:first {{ border-top-left-radius: {RADIUS_CARD - 1}px; }}
QHeaderView::section:last {{
    border-right: none;
    border-top-right-radius: {RADIUS_CARD - 1}px;
}}
QHeaderView::section:only-one {{
    border-right: none;
    border-top-left-radius: {RADIUS_CARD - 1}px;
    border-top-right-radius: {RADIUS_CARD - 1}px;
}}
QListWidget {{ padding: 4px; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* ---- inputs ---------------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QDateEdit, QComboBox, QSpinBox {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_INPUT}px;
    padding: 7px 10px;
    selection-background-color: {p.primary};
    selection-color: {p.primary_text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QDateEdit:focus, QComboBox:focus {{
    border: 1px solid {p.primary};
}}
QLineEdit:read-only {{ background: {p.surface_alt}; color: {p.text_muted}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_INPUT}px;
    selection-background-color: {p.primary_soft};
    selection-color: {p.text};
    padding: 4px;
}}

/* ---- buttons --------------------------------------------------------- */
QPushButton {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_PILL}px;
    padding: 8px 16px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p.primary_soft}; border-color: {p.primary}; }}
QPushButton:pressed {{ background: {p.primary_soft}; }}
QPushButton:disabled {{
    background: {p.surface_alt}; color: {p.text_faint};
    border-color: {p.border};
}}
QPushButton#primary {{
    background: {p.primary}; color: {p.primary_text};
    border: none; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {p.primary_hover}; }}
QPushButton#primary:pressed {{ background: {p.primary_press}; }}
/* An ID selector outranks QPushButton:disabled, so a disabled primary needs
   its own dimmed rule -- otherwise it stays fully coloured and looks live. */
QPushButton#primary:disabled {{
    background: {p.surface_alt}; color: {p.text_faint}; font-weight: 600;
}}
QPushButton#danger {{ color: {p.danger}; border-color: {p.border_strong}; }}
QPushButton#danger:hover {{
    background: {p.danger_soft}; border-color: {p.danger}; color: {p.danger};
}}
QPushButton#ghost {{
    background: transparent; border: none; color: {p.text_muted};
}}
QPushButton#ghost:hover {{ background: {p.primary_soft}; color: {p.text}; }}
/* Speak buttons are fixed at 46px wide; the global 16px side padding would
   leave the 🔊 glyph ~12px of content box and clip it at some DPI/font
   combinations. */
QPushButton#speak {{ padding: 8px 0; min-width: 0; }}
/* − / + steppers: the base 16px side padding would clip a single glyph in a
   34px-wide button, so drop it and centre a slightly larger symbol. */
QPushButton#stepper {{
    padding: 0; min-width: 0; font-size: 16px; font-weight: 700;
}}

/* ---- misc ------------------------------------------------------------ */
QGroupBox {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_CARD}px;
    margin-top: 11px;
    padding: 18px 16px 14px 16px;
    font-weight: 700;
    color: {p.text};
}}
QGroupBox::title {{
    /* An outlined pill sitting on the border line, so the heading reads as a
       label attached to the box rather than text floating on the page. */
    subcontrol-origin: margin;
    left: 16px;
    padding: 3px 12px;
    background: {p.primary_soft};
    border: 1px solid {p.border_strong};
    border-radius: 10px;
    color: {p.text};
    font-weight: 500;
}}
QCheckBox, QRadioButton {{ color: {p.text}; spacing: 7px; }}
QLabel#hint {{ color: {p.text_muted}; }}
QLabel#title {{ font-size: 13pt; font-weight: 700; color: {p.text}; }}
QLabel#section {{ font-size: 11pt; font-weight: 700; color: {p.text}; }}
QStatusBar {{ background: {p.bg}; color: {p.text_muted}; }}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: {p.bg}; color: {p.text}; padding: 2px; }}
QMenuBar::item {{ padding: 6px 11px; border-radius: 8px; background: transparent; }}
QMenuBar::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
QMenu {{
    background: {p.surface}; color: {p.text};
    border: 1px solid {p.border}; border-radius: {RADIUS_INPUT}px; padding: 6px;
}}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 7px; }}
QMenu::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QSplitter::handle {{ background: transparent; }}
/* Scrollbars sit *inside* a rounded frame, and Qt does not clip children to a
   stylesheet border-radius -- so a bar running the full width shot straight
   past the curve while the frame turned away from it. Insetting each bar by
   the corner radius along its own axis keeps it clear of both corners, and
   the small cross-axis margin lifts it off the border line. */
QScrollBar:vertical {{
    background: transparent; width: 12px;
    margin: {RADIUS_CARD}px 3px {RADIUS_CARD}px 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong}; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{
    background: transparent; height: 12px;
    margin: 0 {RADIUS_CARD}px 3px {RADIUS_CARD}px;
}}
QScrollBar::handle:horizontal {{
    background: {p.border_strong}; border-radius: 4px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{
    background: {p.text}; color: {p.surface};
    border: none; border-radius: 7px; padding: 6px 9px;
}}
QProgressBar {{
    background: {p.surface_alt}; border: none; border-radius: 5px;
    height: 8px; text-align: center; color: {p.text_muted};
}}
QProgressBar::chunk {{ background: {p.primary}; border-radius: 5px; }}
"""


def apply(app, palette_key: str | None = None) -> Palette:
    """Install the palette on the QApplication and return it."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QStyleFactory

    p = PALETTES.get(palette_key or DEFAULT_PALETTE, VIOLET)

    # Fusion honours the palette we set; the native Windows style keeps
    # pulling colours from the OS theme instead.
    app.setStyle(QStyleFactory.create("Fusion"))

    qp = QPalette()
    qp.setColor(QPalette.Window, QColor(p.bg))
    qp.setColor(QPalette.WindowText, QColor(p.text))
    qp.setColor(QPalette.Base, QColor(p.surface))
    qp.setColor(QPalette.AlternateBase, QColor(p.surface_alt))
    qp.setColor(QPalette.Text, QColor(p.text))
    qp.setColor(QPalette.Button, QColor(p.surface))
    qp.setColor(QPalette.ButtonText, QColor(p.text))
    qp.setColor(QPalette.Highlight, QColor(p.primary))
    qp.setColor(QPalette.HighlightedText, QColor(p.primary_text))
    qp.setColor(QPalette.ToolTipBase, QColor(p.text))
    qp.setColor(QPalette.ToolTipText, QColor(p.surface))
    qp.setColor(QPalette.PlaceholderText, QColor(p.text_faint))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        qp.setColor(QPalette.Disabled, role, QColor(p.text_faint))
    app.setPalette(qp)
    app.setStyleSheet(build_style(p))
    return p
