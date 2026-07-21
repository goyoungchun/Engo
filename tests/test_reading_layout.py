"""The reading tab's two panels must never overlap, however wide the left.

A long article headline used to force the right panel's minimum width past
800px; inside the splitter that pushed it over the left panel, which then
showed through clipped. And the fetched article body was capped so short it
arrived truncated. Both are checked here against the real tab.

Run:  .venv\\Scripts\\python.exe tests\\test_reading_layout.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ENGO_HOME"] = tempfile.mkdtemp(prefix="engo_layout_")
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QElapsedTimer, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplitter        # noqa: E402

app = QApplication.instance() or QApplication([])

from app import db, news, repo, theme, tts                   # noqa: E402

db.connect()
palette = theme.apply(app, "violet")

_failures: list[str] = []
LONG = ("'The Trojan Teddy Bear': The promise and peril of childhood in the "
        "age of artificial intelligence and what it means for everyone")


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def pump(ms: int) -> None:
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()


def run() -> None:
    for _ in range(3):
        repo.create_passage(LONG, "One sentence. Two sentence. Three now.",
                            source_url="https://theconversation.com/x")

    from app.ui.main_window import MainWindow
    win = MainWindow(palette, lambda: 0)
    win.resize(1000, 700)
    win.show()
    pump(400)
    win.tabs.setCurrentIndex(1)
    pump(400)
    tab = win._built[1]
    tab.list.setCurrentRow(0)
    pump(200)

    splitter = tab.findChild(QSplitter)
    left, right = splitter.widget(0), splitter.widget(1)

    def overlaps() -> bool:
        lx = left.mapTo(tab, QPoint(0, 0)).x()
        rx = right.mapTo(tab, QPoint(0, 0)).x()
        return (lx + left.width()) > rx + 2

    print("[제목이 패널 너비를 강제하지 않는다]")
    check("오른쪽 최소너비가 500 이하", right.minimumWidth() <= 500,
          str(right.minimumWidth()))
    check("긴 제목이 …로 줄어든다", "…" in _shown(tab.title_label),
          _shown(tab.title_label)[-24:])
    check("전체 제목은 보존된다 (툴팁·데이터)", tab.title_label.text() == LONG)

    print("\n[왼쪽을 넓혀도 겹치지 않는다]")
    for target in ([650, 300], [750, 250], [820, 180]):
        splitter.setSizes(target)
        pump(200)
        check(f"sizes≈{target}: 안 겹침", not overlaps(),
              f"(실제 {splitter.sizes()})")
    check("왼쪽이 실제로 넓어졌다", left.width() >= 300, str(left.width()))

    print("\n[더 좁은 창]")
    win.resize(900, 680)
    pump(200)
    splitter.setSizes([560, 300])
    pump(200)
    check("좁은 창에서도 안 겹침", not overlaps(),
          f"(sizes {splitter.sizes()})")

    print("\n[스플리터 드래그가 매 프레임 행 높이를 재계산하지 않는다]")
    # resizeRowsToContents lays out every cell; running it per frame of a drag
    # made dragging lag. It must be debounced to one pass after the drag.
    win.resize(1300, 720)
    pump(200)
    calls = {"n": 0}
    original = tab.table.resizeRowsToContents
    tab._refit.timeout.disconnect()
    tab._refit.timeout.connect(lambda: (calls.__setitem__("n", calls["n"] + 1),
                                        original()))
    base = splitter.sizes()[0]
    for i in range(30):
        splitter.setSizes([base + i * 8, splitter.sizes()[1]])
        app.processEvents()
    during = calls["n"]
    pump(300)                      # let the debounce settle
    check("드래그 30프레임에 재계산은 몇 번뿐", during <= 3,
          f"(드래그 중 {during}회)")
    check("드래그가 멈추면 한 번 재계산된다", calls["n"] > during,
          f"({calls['n']}회)")

    print("\n[기사 본문이 잘리지 않는다]")
    check("본문 상한이 넉넉하다 (>=20000)", news.MAX_BODY >= 20000,
          str(news.MAX_BODY))
    articles, error = news.fetch(["conversation"], ["world"], 2)
    if error == "news_offline":
        print("  건너뜀: 네트워크 없음")
    else:
        longest = max((len(a.text) for a in articles), default=0)
        check("The Conversation 전체 본문이 온다 (>3000자)", longest > 3000,
              f"({[len(a.text) for a in articles]})")

    print("\n[긴 문장이 셀 안에서 잘리지 않는다]")
    from PySide6.QtGui import QFontMetrics
    from app.ui.reading_tab import COL_EN
    body = ("From tomatoes and berries to lettuce and peppers, shoppers are "
            "feeling real sticker shock in the produce aisle this year. "
            "Short. "
            "Another quite long sentence that has to wrap across several lines "
            "in the narrow English column and still show its very last word.")
    pid = repo.create_passage("Clip test", body)
    win.resize(1000, 700)
    pump(200)
    tab.reload()
    _select(tab, pid)
    pump(300)
    clipped = 0
    for r in range(tab.table.rowCount()):
        item = tab.table.item(r, COL_EN)
        fm = QFontMetrics(item.font())
        need = fm.boundingRect(0, 0, tab.table.columnWidth(COL_EN) - 10, 100000,
                               Qt.TextWordWrap, item.text()).height()
        if tab.table.rowHeight(r) < need - 2:
            clipped += 1
    check("어떤 행도 잘리지 않는다", clipped == 0, f"({clipped}개 잘림)")

    print("\n[지문 길이 배지: 짧음 / 중간 / 김]")
    from app.ui.reading_tab import _length_label
    from app import i18n as _i18n
    _i18n.set_language("ko")
    check("6문장은 짧음", _length_label(6) == "짧음", _length_label(6))
    check("18문장은 중간", _length_label(18) == "중간", _length_label(18))
    check("40문장은 김", _length_label(40) == "김", _length_label(40))
    check("경계 10/11: 10은 짧음, 11은 중간",
          _length_label(10) == "짧음" and _length_label(11) == "중간")
    check("경계 25/26: 25는 중간, 26은 김",
          _length_label(25) == "중간" and _length_label(26) == "김")
    # the badge actually reaches the list and header
    long_body = " ".join(f"Sentence number {i} here now." for i in range(40))
    lpid = repo.create_passage("Long one", long_body)
    tab.reload()
    _select(tab, lpid)
    pump(200)
    listed = next(tab.list.item(i).text() for i in range(tab.list.count())
                  if tab.list.item(i).data(Qt.UserRole) == lpid)
    check("목록에 '김' 배지가 보인다", "김" in listed, repr(listed))
    check("헤더에도 '김' 배지가 보인다", "김" in tab.progress_label.text(),
          tab.progress_label.text())

    print("\n[소제목이 문장과 구분된다]")
    from app import news as _news
    with_head = ("Intro sentence here now.\n"
                 "## Section One Title\n"
                 "Body after the heading here. Second body sentence here now.\n"
                 "## Section Two Title\n"
                 "Closing sentence of the passage here.")
    hid = repo.create_passage("Heading test", with_head)
    tab.reload()
    _select(tab, hid)
    pump(300)
    tb = tab.table
    heading_rows = [r for r in range(tb.rowCount())
                    if tb.columnSpan(r, COL_EN) == 3]
    check("소제목 행이 2개, 3열 병합", len(heading_rows) == 2, str(heading_rows))
    for r in heading_rows:
        check(f"행{r}: 소제목에 '##'가 안 보인다",
              "##" not in tb.item(r, COL_EN).text(), tb.item(r, COL_EN).text())
        no_item = tb.item(r, 0)
        check(f"행{r}: 번호가 없다", no_item is None or no_item.text() == "",
              repr(no_item.text()) if no_item else "None")
    # 4 sentences (the middle body line is two), 2 headings excluded.
    check("진행 표시가 소제목을 세지 않는다 (4문장)",
          "/ 4" in tab.progress_label.text(), tab.progress_label.text())

    print("\n[지문 여러 개 선택 삭제]")
    from PySide6.QtWidgets import QListWidget, QMessageBox
    check("지문 목록이 다중 선택 모드",
          tab.list.selectionMode() == QListWidget.ExtendedSelection)
    for _ in range(4):
        repo.create_passage("지울 지문", "One here. Two here.")
    tab.reload()
    pump(150)
    before = repo.count_rows("passages")
    # exactly three: clear the reload's current-item selection first
    tab.list.clearSelection()
    for i in range(3):
        tab.list.item(i).setSelected(True)
    pump(50)
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    tab.delete_passage()
    QMessageBox.question = original
    pump(150)
    check("선택한 3개가 한 번에 지워졌다",
          repo.count_rows("passages") == before - 3,
          f"({before} → {repo.count_rows('passages')})")

    win.prepare_quit()
    win.close()
    tts.shutdown()
    app.quit()


def _select(tab, passage_id: str) -> None:
    for i in range(tab.list.count()):
        if tab.list.item(i).data(Qt.UserRole) == passage_id:
            tab.list.setCurrentRow(i)
            return


def _shown(label) -> str:
    """The text actually painted (elided), not the stored full text."""
    from PySide6.QtWidgets import QLabel
    return QLabel.text(label)


QTimer.singleShot(300, run)
app.exec()

print()
if _failures:
    print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
    sys.exit(1)
print("모든 원문 해석 레이아웃 테스트 통과")
