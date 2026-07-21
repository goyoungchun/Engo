"""Motion: a sliding tab indicator, sliding pages, and springy buttons.

All three are deliberately short (under a third of a second) and all three
degrade to an instant change when the widget is not on screen -- an animation
that runs while nothing is visible only delays the result, and tests would
have to sleep for it.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation,
    QRect, Qt, Property,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStackedWidget, QTabBar

from .. import theme

INDICATOR_MS = 260
PAGE_MS = 240
JELLY_MS = 190


class SlidingTabBar(QTabBar):
    """Tab bar whose selection pill slides from the old tab to the new one.

    The pill is painted here rather than by the stylesheet, because a
    stylesheet background is pinned to its tab and cannot travel between them.
    """

    def __init__(self, palette: theme.Palette, parent=None):
        super().__init__(parent)
        self.palette_ = palette
        self.setDrawBase(False)
        self.setExpanding(False)
        self._pill = QRect()
        self._anim = QPropertyAnimation(self, b"pillRect", self)
        self._anim.setDuration(INDICATOR_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.currentChanged.connect(self._move_pill)

    # -- animated property ------------------------------------------------
    def get_pill(self) -> QRect:
        return self._pill

    def set_pill(self, rect: QRect) -> None:
        self._pill = rect
        self.update()

    pillRect = Property(QRect, get_pill, set_pill)

    # -- behaviour --------------------------------------------------------
    def restyle(self, palette: theme.Palette) -> None:
        self.palette_ = palette
        self.update()

    def _target(self, index: int) -> QRect:
        return self.tabRect(index).adjusted(0, 3, 0, -3)

    def _move_pill(self, index: int) -> None:
        if index < 0:
            return
        target = self._target(index)
        if not self.isVisible() or self._pill.isNull():
            self._anim.stop()
            self.set_pill(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._pill)
        self._anim.setEndValue(target)
        self._anim.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pill.isNull() and self.currentIndex() >= 0:
            self.set_pill(self._target(self.currentIndex()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.currentIndex() >= 0 and self._anim.state() != QAbstractAnimation.Running:
            self.set_pill(self._target(self.currentIndex()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if not self._pill.isNull():
            path = QPainterPath()
            path.addRoundedRect(self._pill, self._pill.height() / 2,
                                self._pill.height() / 2)
            painter.fillPath(path, QColor(self.palette_.primary))

        current = self.currentIndex()
        for index in range(self.count()):
            rect = self.tabRect(index)
            painter.setPen(QColor(self.palette_.primary_text if index == current
                                  else self.palette_.text_muted))
            font = painter.font()
            font.setBold(index == current)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self.tabText(index))
        painter.end()

    def tabSizeHint(self, index: int):
        size = super().tabSizeHint(index)
        size.setWidth(size.width() + 24)
        size.setHeight(max(size.height(), 38))
        return size


class PageSlider(QObject):
    """Slides the whole page sideways when the tab changes.

    Works on a snapshot: the outgoing and incoming pages are drawn into one
    pixmap and that single overlay is moved. Animating the live widgets would
    mean fighting the stack's own geometry management, and a half-finished
    animation would leave a page at the wrong position.
    """

    def __init__(self, tabs, parent=None):
        super().__init__(parent or tabs)
        self.tabs = tabs
        self.stack = tabs.findChild(QStackedWidget)
        self._overlay: QLabel | None = None
        self._anim: QPropertyAnimation | None = None
        self._previous = tabs.currentIndex()
        self._before: QPixmap | None = None
        self._in_changed = False
        tabs.currentChanged.connect(self._on_changed)

    def snapshot(self) -> None:
        """Grab the page about to be left. Called before the index changes."""
        if self.stack is None or not self.stack.isVisible():
            self._before = None
            return
        page = self.stack.currentWidget()
        self._before = page.grab() if page is not None else None

    def _on_changed(self, index: int) -> None:
        old, self._previous = self._previous, index
        if (self.stack is None or not self.stack.isVisible()
                or self._before is None or old == index):
            self._before = None
            return
        if self._in_changed:
            # processEvents below can re-enter this slot if the user clicks a
            # third tab mid-transition; the nested run would build an overlay
            # the outer run then destroys, garbling the slide. Skip the
            # animation for the nested switch -- the stack itself is already
            # showing the right page.
            self._before = None
            return
        self._in_changed = True
        try:
            self._run_slide(old, index)
        finally:
            self._in_changed = False

    def _run_slide(self, old: int, index: int) -> None:
        before, self._before = self._before, None
        # Let the incoming page lay itself out before it is photographed.
        QApplication.processEvents()
        after = self.stack.currentWidget()
        if after is None:
            return
        after_pix = after.grab()

        width = self.stack.width()
        height = self.stack.height()
        forward = index > old

        sheet = QPixmap(width * 2, height)
        sheet.fill(Qt.transparent)
        painter = QPainter(sheet)
        if forward:
            painter.drawPixmap(0, 0, before)
            painter.drawPixmap(width, 0, after_pix)
            start, end = 0, -width
        else:
            painter.drawPixmap(0, 0, after_pix)
            painter.drawPixmap(width, 0, before)
            start, end = -width, 0
        painter.end()

        self._clear()
        overlay = QLabel(self.stack)
        overlay.setPixmap(sheet)
        overlay.setGeometry(start, 0, width * 2, height)
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

        anim = QPropertyAnimation(overlay, b"pos", self)
        anim.setDuration(PAGE_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(QPoint(start, 0))
        anim.setEndValue(QPoint(end, 0))
        anim.finished.connect(self._clear)
        self._anim = anim
        anim.start()

    def _clear(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        self._anim = None


class JellyFilter(QObject):
    """Squash-and-spring on button press.

    Animates the button's own geometry. Layouts only reassign geometry when
    something invalidates them, so the wobble survives the click; the target
    rectangle is remembered and restored so a stray relayout cannot leave a
    button stuck at the squashed size.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anims: dict[int, QPropertyAnimation] = {}

    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, QPushButton) and obj.isEnabled():
            if event.type() == QEvent.MouseButtonPress:
                self._squash(obj)
            elif event.type() == QEvent.MouseButtonRelease:
                self._spring(obj)
        return super().eventFilter(obj, event)

    def _rest_rect(self, button: QPushButton) -> QRect:
        rect = button.property("_jellyRest")
        if rect is None:
            rect = button.geometry()
            button.setProperty("_jellyRest", rect)
        return rect

    def _animate(self, button: QPushButton, target: QRect, curve, ms: int) -> None:
        key = id(button)
        existing = self._anims.pop(key, None)
        if existing is not None:
            existing.stop()
        # Parented to the BUTTON, not this filter: the filter lives for the
        # whole process, and an animation interrupted by its target's death
        # never fires finished -- each such case would leak a dict entry and
        # a QPropertyAnimation forever. Owned by the button, both die with it.
        anim = QPropertyAnimation(button, b"geometry", button)
        anim.setDuration(ms)
        anim.setEasingCurve(curve)
        anim.setStartValue(button.geometry())
        anim.setEndValue(target)
        anim.finished.connect(lambda: self._anims.pop(key, None))
        anim.destroyed.connect(lambda: self._anims.pop(key, None))
        self._anims[key] = anim
        anim.start()

    def _squash(self, button: QPushButton) -> None:
        rest = self._rest_rect(button)
        # Squash both ways now, but the height only a little. Shrinking the
        # height too far turns the pill square -- Qt draws square corners once
        # border-radius exceeds half the height -- so the squashed height is
        # never allowed below twice the corner radius.
        dx = max(3, rest.width() // 14)
        dy = max(2, rest.height() // 14)
        floor = 2 * theme.RADIUS_PILL
        if rest.height() - 2 * dy < floor:
            dy = max(0, (rest.height() - floor) // 2)
        self._animate(button, rest.adjusted(dx, dy, -dx, -dy),
                      QEasingCurve.OutQuad, 90)

    def _spring(self, button: QPushButton) -> None:
        rest = button.property("_jellyRest")
        if rest is None:
            return
        # OutBack overshoots past the resting size and settles back -- that
        # overshoot is what reads as "jelly" rather than a plain resize.
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(3.4)
        self._animate(button, rest, curve, JELLY_MS)
        button.setProperty("_jellyRest", None)


_jelly: JellyFilter | None = None


def install(widget) -> None:
    """Give every button under `widget` the press animation."""
    global _jelly
    if _jelly is None:
        _jelly = JellyFilter(QApplication.instance())
    for button in widget.findChildren(QPushButton):
        button.removeEventFilter(_jelly)
        button.installEventFilter(_jelly)
