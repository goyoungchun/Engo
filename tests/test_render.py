"""Rendering regression tests -- these need a real display.

Why they exist: a stylesheet can make a control *invisible* while every
programmatic check still passes. The sticky note's title bar buttons were laid
out at the right size, reported visible=True and enabled=True, and drew
absolutely nothing, because the app-wide `QPushButton { padding: 5px 13px }`
left a 22x22 button with no room for its glyph. Only counting painted pixels
catches that.

These cannot run under QT_QPA_PLATFORM=offscreen: that platform has no font
engine here and paints every glyph as the same placeholder box, so both a
working and a broken control would look identical.

A related trap, for anyone tempted to verify a launcher this way: asking
Windows to enumerate top-level windows (EnumWindows) from a separate tool
process is not a test of whether the app's window appeared. A spawned process
can land on a window station the enumerating process cannot see, and then
*every* launch looks broken -- python.exe and pythonw.exe alike -- while the
app itself correctly reports isVisible() == True with a valid winId. Ask the
application, not the desktop.

Run:  .venv\\Scripts\\python.exe tests\\test_render.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = tempfile.mkdtemp(prefix="studyenglish_render_")
os.environ["STUDYENGLISH_HOME"] = _ROOT
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app import db, i18n, repo, theme                   # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def ink(child, root) -> int:
    """Distinct colours painted where `child` sits inside `root`.

    Two coordinate traps, both of which silently produce meaningless numbers:

    * QWidget.grab() returns *physical* pixels (1.25x on this display) while
      geometry() is in logical pixels, so the rect has to be scaled or the
      sample lands somewhere else entirely.
    * child.geometry() is relative to the child's parent, not to `root`, so
      the position has to be mapped.

    A result of 1 means the region is a flat block of colour -- nothing drawn.
    """
    from PySide6.QtCore import QPoint

    image = root.grab().toImage()
    scale = image.width() / max(root.width(), 1)
    top_left = child.mapTo(root, QPoint(0, 0))

    x0 = int(top_left.x() * scale)
    y0 = int(top_left.y() * scale)
    x1 = min(int((top_left.x() + child.width()) * scale), image.width())
    y1 = min(int((top_left.y() + child.height()) * scale), image.height())

    seen = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            seen.add(image.pixelColor(x, y).name())
    return len(seen)


def _luminance(color) -> float:
    def channel(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(color.red()) + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def contrast(root, child) -> float:
    """WCAG contrast between the lightest and darkest pixel where `child` sits.

    `root` must be a widget with an OPAQUE background -- grabbing a widget
    whose own background is semi-transparent makes Qt fill the pixmap with
    white, so light-on-dark text measures as light-on-white and reports a
    failure that does not exist on screen. Pass the note, not the item.
    """
    from PySide6.QtCore import QPoint

    image = root.grab().toImage()
    scale = image.width() / max(root.width(), 1)
    tl = child.mapTo(root, QPoint(0, 0))
    x0, y0 = int(tl.x() * scale), int(tl.y() * scale)
    x1 = min(int((tl.x() + child.width()) * scale), image.width())
    y1 = min(int((tl.y() + child.height()) * scale), image.height())

    lums = [_luminance(image.pixelColor(x, y))
            for y in range(y0, y1) for x in range(x0, x1)]
    if not lums:
        return 0.0
    lo, hi = min(lums), max(lums)
    return (hi + 0.05) / (lo + 0.05)


def dominant(root, child) -> str:
    """Most common colour where `child` sits inside `root`."""
    from collections import Counter
    from PySide6.QtCore import QPoint

    image = root.grab().toImage()
    scale = image.width() / max(root.width(), 1)
    tl = child.mapTo(root, QPoint(0, 0))
    x0, y0 = int(tl.x() * scale), int(tl.y() * scale)
    x1 = min(int((tl.x() + child.width()) * scale), image.width())
    y1 = min(int((tl.y() + child.height()) * scale), image.height())
    counts = Counter(image.pixelColor(x, y).name()
                     for y in range(y0, y1) for x in range(x0, x1))
    return counts.most_common(1)[0][0] if counts else ""


def close_to(a: str, b: str, tolerance: int = 20) -> bool:
    if not a or not b:
        return False
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return all(abs(x - y) <= tolerance for x, y in zip(pa, pb))


def run(app: QApplication, palette) -> None:
    from app.ui.sticky import ReviewItem, StickyManager

    for i in range(6):
        repo.save_row("expressions", {
            "english": f"expression {i}", "korean": f"뜻 {i}",
            "studied_on": repo.today()})

    manager = StickyManager(palette)
    note = manager.open_new("expressions", "today")
    note.resize(330, 400)
    note.show()
    for _ in range(10):
        app.processEvents()

    print("\n[스티키 제목 표시줄]")
    check("제목 텍스트가 그려짐", ink(note.title_label, note.titlebar) > 2)

    buttons = note.titlebar.findChildren(QPushButton)
    check("버튼 4개", len(buttons) == 4, f"({len(buttons)}개)")
    for button in buttons:
        colors = ink(button, note.titlebar)
        check(f"버튼 {button.text()!r} 글리프가 실제로 그려짐", colors > 2,
              f"(색 {colors}개)")

    print("\n[복습 항목]")
    items = [i for i in note._items if isinstance(i, ReviewItem)]
    check("항목이 생성됨", bool(items), f"({len(items)}개)")
    check("한 묶음 상한 30", len(items) <= 30, f"({len(items)}개)")

    item = items[0]
    check("영어 원문이 그려짐", ink(item.english, item) > 2)
    check("가려진 상태에도 안내 문구가 보임", ink(item.korean, item) > 2)

    # 뜻을 펼치면 그때 버튼이 만들어지고, 그 버튼도 실제로 보여야 한다.
    check("가린 상태에서는 버튼을 만들지 않음", item._buttons is None)
    item.reveal(True)
    for _ in range(10):
        app.processEvents()
    check("펼치면 버튼이 생김", item._buttons is not None)

    for button in item._buttons.findChildren(QPushButton):
        colors = ink(button, item)
        check(f"'{button.text()}' 버튼이 그려짐", colors > 2, f"(색 {colors}개)")

    print("\n[메인 창]")
    from app.ui.main_window import MainWindow, TAB_KEYS
    from app.i18n import t
    window = MainWindow(palette, lambda: manager.count)
    window.resize(1040, 660)
    window.show()
    for _ in range(10):
        app.processEvents()

    for i, key in enumerate(TAB_KEYS):
        window.tabs.setCurrentIndex(i)
        for _ in range(3):
            app.processEvents()
        check(f"탭 {i} 이름 유지", window.tabs.tabText(i) == t(key),
              f"({window.tabs.tabText(i)!r})")
        current = window.tabs.currentWidget()
        check(f"탭 {i} 내용이 그려짐", ink(current, current) > 3)

    window.tabs.setCurrentIndex(0)
    for _ in range(3):
        app.processEvents()
    expressions = window._built[0]
    check("표 내용이 그려짐", ink(expressions.view, expressions) > 3)

    print("\n[강조 버튼이 실제로 채워지는지]")
    # A stylesheet on an ancestor can silently strip the fill and leave a
    # ghost button, which still reports visible=True and the right geometry.
    data_tab = window._built[4]
    for name, button, root in (
            ("＋ 새로 추가", expressions.new_btn, expressions),
            ("저장", expressions.save_btn, expressions),
            ("파일로 내보내기", data_tab.export_btn, data_tab),
    ):
        colour = dominant(root, button)
        check(f"'{name}' 버튼이 강조색으로 채워짐",
              close_to(colour, palette.primary),
              f"(칠해진 색 {colour}, 기대 {palette.primary})")

    print("\n[버튼을 누르는 동안 모서리가 둥근 채로 유지되는지]")
    # Qt draws square corners the moment border-radius exceeds half the height.
    # The press animation squashes the height a little now, so what matters is
    # that it never squashes past that line: the corners must stay round every
    # frame, and the height, though it shrinks, must not drop below 2*radius.
    from PySide6.QtCore import QElapsedTimer, QEvent, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt as _Qt

    def pump(ms):
        timer = QElapsedTimer()
        timer.start()
        while timer.elapsed() < ms:
            app.processEvents()

    def corner_is_round(root, widget) -> bool:
        image = root.grab().toImage()
        scale = image.width() / max(root.width(), 1)
        tl = widget.mapTo(root, QPoint(0, 0))
        x0, y0 = int(tl.x() * scale), int(tl.y() * scale)
        corner = image.pixelColor(x0 + 1, y0 + 1).name()
        middle = image.pixelColor(x0 + int(widget.width() * scale / 2),
                                  y0 + int(widget.height() * scale / 2)).name()
        return corner != middle

    radius_floor = 2 * theme.RADIUS_PILL
    button = expressions.new_btn
    rest_height = button.height()
    app.sendEvent(button, QMouseEvent(
        QEvent.MouseButtonPress, QPoint(5, 5), _Qt.LeftButton, _Qt.LeftButton,
        _Qt.NoModifier))
    square_frames, below_floor = 0, 0
    min_height = rest_height
    for _ in range(5):
        pump(25)
        if not corner_is_round(expressions, button):
            square_frames += 1
        min_height = min(min_height, button.height())
        if button.height() < radius_floor:
            below_floor += 1
    app.sendEvent(button, QMouseEvent(
        QEvent.MouseButtonRelease, QPoint(5, 5), _Qt.LeftButton, _Qt.LeftButton,
        _Qt.NoModifier))
    for _ in range(5):
        pump(25)
        if not corner_is_round(expressions, button):
            square_frames += 1
        if button.height() < radius_floor:
            below_floor += 1
    pump(300)
    check("누르는 동안 사각형이 되는 프레임 없음", square_frames == 0,
          f"({square_frames}프레임)")
    check("누르면 높이도 약간 줄어든다", min_height < rest_height,
          f"({rest_height} → {min_height})")
    check("높이가 알약 한계(2*radius) 밑으로는 안 내려간다", below_floor == 0,
          f"({below_floor}프레임, 한계 {radius_floor})")
    check("애니메이션 후 원래 크기로 복귀", button.height() == rest_height)

    print("\n[스크롤바가 둥근 모서리를 침범하지 않는지]")
    # Qt does not clip children to a stylesheet border-radius, so a scrollbar
    # spanning the full width ran straight past the corner the frame curved
    # away from. Its handle must stay outside the corner square entirely.
    from PySide6.QtCore import QPoint as _QPoint
    view = expressions.view
    handle_colour = palette.border_strong.lower()
    radius = theme.RADIUS_CARD
    image = expressions.grab().toImage()
    scale = image.width() / max(expressions.width(), 1)
    origin = view.mapTo(expressions, _QPoint(0, 0))

    intrusions = 0
    for corner_x, corner_y in ((origin.x(), origin.y() + view.height() - radius),
                               (origin.x() + view.width() - radius,
                                origin.y() + view.height() - radius)):
        for dy in range(radius):
            for dx in range(radius):
                x = int((corner_x + dx) * scale)
                y = int((corner_y + dy) * scale)
                if 0 <= x < image.width() and 0 <= y < image.height():
                    if image.pixelColor(x, y).name() == handle_colour:
                        intrusions += 1
    check("스크롤바가 아래쪽 두 모서리를 침범하지 않음", intrusions == 0,
          f"({intrusions}픽셀)")

    # Measure where the handle is actually painted. A stylesheet `margin` on a
    # scrollbar moves the drawn subcontrols but leaves contentsRect() at zero,
    # so asking the widget would report an inset that is not there.
    bar = view.horizontalScrollBar()
    bar_top = bar.mapTo(expressions, _QPoint(0, 0)).y()
    row = int((bar_top + bar.height() // 2) * scale)
    left_inset = None
    for dx in range(view.width()):
        x = int((origin.x() + dx) * scale)
        if 0 <= x < image.width() and 0 <= row < image.height():
            if image.pixelColor(x, row).name() == handle_colour:
                left_inset = dx
                break
    check("가로 스크롤바 핸들이 모서리 반경만큼 들어와 있음",
          left_inset is not None and left_inset >= radius - 2,
          f"(핸들 시작 {left_inset}px, 모서리 반경 {radius}px)")

    print("\n[탭바가 검색바와 같은 선에서 시작]")
    from PySide6.QtCore import QPoint
    tabbar_x = window.tabs.tabBar().mapTo(window, QPoint(0, 0)).x()
    search_x = expressions.search_box.mapTo(window, QPoint(0, 0)).x()
    check("탭바 왼쪽 = 검색바 왼쪽", abs(tabbar_x - search_x) <= 2,
          f"(탭바 {tabbar_x}, 검색 {search_x})")

    print("\n[입력칸이 겹치지 않는지]")
    for idx, name in ((2, "외우고 싶은 문장"), (3, "문법")):
        window.tabs.setCurrentIndex(idx)
        for _ in range(8):
            app.processEvents()
        tab = window._built[idx]
        bottoms = []
        overlaps = 0
        for field in tab.spec["fields"]:
            w = tab._editors[field.key]
            top = w.mapTo(tab.editor_card, QPoint(0, 0)).y()
            if bottoms and top < bottoms[-1]:
                overlaps += 1
            bottoms.append(top + w.height())
        check(f"{name} 탭 입력칸 겹침 없음", overlaps == 0, f"({overlaps}건)")

    # and again at a height too small for the form -- the case that broke it
    window.resize(1040, 520)
    for _ in range(10):
        app.processEvents()
    tab = window._built[3]
    bottoms, overlaps = [], 0
    for field in tab.spec["fields"]:
        w = tab._editors[field.key]
        top = w.mapTo(tab.editor_card, QPoint(0, 0)).y()
        if bottoms and top < bottoms[-1]:
            overlaps += 1
        bottoms.append(top + w.height())
    check("창이 낮아도 겹치지 않음", overlaps == 0, f"({overlaps}건)")
    window.resize(1040, 660)
    window.tabs.setCurrentIndex(0)
    for _ in range(8):
        app.processEvents()

    print("\n[탭을 옮길 때 엉뚱한 창이 뜨지 않는지]")
    # A widget made visible before it has a parent becomes a top-level window
    # of its own. That flashed a stray 46x36 speak button on screen on every
    # tab switch -- visible for a frame, then gone, and easy to miss.
    from PySide6.QtCore import QEvent as _QEvent, QObject as _QObject
    from PySide6.QtWidgets import QWidget as _QWidget

    strays = []

    class _Watcher(_QObject):
        def eventFilter(self, obj, event):
            if (event.type() == _QEvent.Show and isinstance(obj, _QWidget)
                    and obj.isWindow() and obj is not window
                    and not obj.windowTitle()):
                strays.append(f"{type(obj).__name__} {obj.width()}x{obj.height()}")
            return False

    watcher = _Watcher()
    app.installEventFilter(watcher)
    for index in (1, 2, 3, 4, 0):
        window.tabs.setCurrentIndex(index)
        for _ in range(10):
            app.processEvents()
    app.removeEventFilter(watcher)
    check("탭 전환 중 뜬 이름 없는 창 없음", not strays,
          f"({', '.join(strays)})" if strays else "")

    print("\n[색 테마 전환]")
    for key in theme.PALETTES:
        p = theme.apply(app, key)
        window.restyle(p)
        manager.restyle(p)
        for _ in range(8):
            app.processEvents()
        check(f"{key} 테마에서 표가 그려짐", ink(expressions.view, expressions) > 3)
        current_note = next(iter(manager.notes.values()))
        check(f"{key} 테마에서 메모지가 그려짐",
              ink(current_note.titlebar, current_note.titlebar) > 2)

        # A dark palette used to leave the note's own text light-on-light.
        items = [i for i in current_note._items if isinstance(i, ReviewItem)]
        if items:
            item = items[0]
            item.reveal(True)
            for _ in range(5):
                app.processEvents()
            ratio = contrast(current_note, item.english)
            check(f"{key} 테마에서 원문 대비 충분", ratio >= 4.5, f"(대비 {ratio:.1f}:1)")
            for button in item._buttons.findChildren(QPushButton):
                r = contrast(current_note, button)
                check(f"{key} 테마에서 '{button.text()}' 대비 충분", r >= 3.0,
                      f"(대비 {r:.1f}:1)")
            item.reveal(False)
            for _ in range(3):
                app.processEvents()
            hint = contrast(current_note, item.korean)
            check(f"{key} 테마에서 안내 문구 대비 충분", hint >= 1.9, f"(대비 {hint:.1f}:1)")
    theme.apply(app, palette.key)
    window.restyle(palette)
    manager.restyle(palette)

    print("\n[한/영 전환]")
    for code in ("en", "ko"):
        i18n.set_language(code)
        window.retranslate()
        manager.rebuild()
        for _ in range(8):
            app.processEvents()
        check(f"{code}: 탭 이름이 바뀜",
              window.tabs.tabText(0) == t("tab_expressions"),
              f"({window.tabs.tabText(0)!r})")
        check(f"{code}: 탭 이름이 비어 있지 않음", bool(window.tabs.tabText(0).strip()))
        check(f"{code}: 메모지가 다시 떠 있음", manager.count == 1)
        new_note = next(iter(manager.notes.values()))
        check(f"{code}: 메모지 제목이 그려짐",
              ink(new_note.title_label, new_note.titlebar) > 2)

    window.prepare_quit()
    window.close()
    manager.close_all(remember=False)
    app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    db.connect()
    palette = theme.apply(app, theme.DEFAULT_PALETTE)

    QTimer.singleShot(300, lambda: run(app, palette))
    app.exec()

    db.close()
    shutil.rmtree(_ROOT, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 렌더링 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
