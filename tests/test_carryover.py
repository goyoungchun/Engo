"""Source and tags carry over from one entry to the next, and autocomplete.

The complaint this answers: adding ten expressions from one article meant
typing the same source and the same tags ten times. So a save remembers them,
and the next blank entry starts pre-filled -- while a field the user clears
stays cleared, because that is how you say you have moved on.

Driven through the real EntryTab so the save -> new-entry flow is exercised,
not just the repo.

Run:  .venv\\Scripts\\python.exe tests\\test_carryover.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ENGO_HOME"] = tempfile.mkdtemp(prefix="engo_carry_")
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication          # noqa: E402

app = QApplication.instance() or QApplication([])

from app import db, repo, theme                     # noqa: E402
from app.ui.common import editor_value, set_editor_value  # noqa: E402

db.connect()
theme.apply(app, "violet")

from app.ui.entry_tab import EntryTab               # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def val(tab, key: str) -> str:
    return editor_value(tab._editors[key])


def type_entry(tab, **fields) -> None:
    """Fill the editor as if typed, then save with Ctrl+S (non-silent)."""
    tab._loading = False
    for key, value in fields.items():
        set_editor_value(tab._editors[key], value)
    tab._mark_dirty()
    tab.save_current()


def main() -> int:
    tab = EntryTab("expressions", theme.apply(app, "violet"))

    print("[저장하면 출처·태그가 다음 새 항목으로 이어진다]")
    type_entry(tab, english="take off", korean="이륙하다",
               source="BBC 6 Minute English", tags="비즈니스, 관용구")
    check("저장 후 새 항목 상태", tab._current_id is None)
    check("출처가 이어졌다", val(tab, "source") == "BBC 6 Minute English",
          repr(val(tab, "source")))
    check("태그가 이어졌다", val(tab, "tags") == "비즈니스, 관용구",
          repr(val(tab, "tags")))
    check("내용 칸은 비어 있다", val(tab, "english") == "" and val(tab, "korean") == "")

    print("\n[내용만 바꿔 연속 입력 -- 출처·태그는 그대로 둔다]")
    # the source/tags are already filled from the carry-over; just add content
    tab._loading = False
    set_editor_value(tab._editors["english"], "wrap up")
    set_editor_value(tab._editors["korean"], "마무리하다")
    tab._mark_dirty()
    tab.save_current()
    same = [dict(r) for r in db.connect().execute(
        "SELECT id, source, tags FROM expressions "
        "WHERE deleted = 0 AND source = ?", ("BBC 6 Minute English",))]
    check("두 항목 모두 같은 출처로 저장됐다", len(same) == 2, f"({len(same)}건)")
    check("두 항목 모두 같은 태그", all(r["tags"] == "비즈니스, 관용구" for r in same))

    print("\n[출처를 비우고 저장하면 빈 값이 이어진다]")
    tab._loading = False
    set_editor_value(tab._editors["source"], "")
    set_editor_value(tab._editors["english"], "no source here")
    tab._mark_dirty()
    tab.save_current()
    check("비운 출처가 다음 항목에도 비어 있다", val(tab, "source") == "",
          repr(val(tab, "source")))
    check("태그는 여전히 이어진다", val(tab, "tags") == "비즈니스, 관용구",
          repr(val(tab, "tags")))

    print("\n[자동완성 후보]")
    type_entry(tab, english="ramp up", korean="늘리다",
               source="The Economist", tags="경제")
    sources = repo.all_sources("expressions")
    check("출처 후보에 이전 값들이 있다",
          "The Economist" in sources and "BBC 6 Minute English" in sources,
          f"({sources})")
    tags = repo.all_tags("expressions")
    check("태그 후보에 이전 값들이 있다",
          "경제" in tags and "관용구" in tags, f"({tags})")

    # the completer models really got the values
    tab._refresh_tags()
    src_model = tab._source_completer.model()
    tag_model = tab._tags_completer.model()
    check("출처 자동완성 모델이 채워졌다",
          "The Economist" in src_model.stringList())
    check("태그 자동완성 모델이 채워졌다", "경제" in tag_model.stringList())

    print("\n[문법 탭: 출처 칸이 없어도 태그는 이어진다]")
    gram = EntryTab("grammar", theme.apply(app, "violet"))
    type_entry(gram, title="가정법 과거", body="if + 과거…", tags="가정법")
    check("문법도 태그가 이어진다", editor_value(gram._editors["tags"]) == "가정법",
          repr(editor_value(gram._editors["tags"])))
    check("문법에는 출처 칸이 없다", "source" not in gram._editors)
    check("출처 후보 조회가 문법에서는 빈 목록",
          repo.all_sources("grammar") == [])

    print("\n[이어받기는 새 항목에만 -- 기존 항목을 열면 그 값이 보인다]")
    first = same[0]["id"]
    tab._load_row(first)
    check("기존 항목은 자기 값을 보여준다",
          val(tab, "source") == "BBC 6 Minute English",
          repr(val(tab, "source")))

    print("\n[기존 항목을 고쳐 저장해도 이어받기 값은 안 바뀐다]")
    # carry is currently "The Economist / 경제" from the last NEW entry.
    # Fixing a typo in this old BBC row must not hijack that.
    tab._loading = False
    set_editor_value(tab._editors["english"], "take off (수정)")
    tab._mark_dirty()
    tab.save_current()
    check("수정 저장 후에도 새 항목 프리필은 최근 새 항목의 출처",
          val(tab, "source") == "The Economist", repr(val(tab, "source")))
    check("태그도 최근 새 항목 것", val(tab, "tags") == "경제",
          repr(val(tab, "tags")))

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 이어받기·자동완성 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
