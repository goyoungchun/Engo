"""Headless tests for the data layer -- no Qt, no display needed.

Run:  .venv\\Scripts\\python.exe -m tests.test_core
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, repo, sync  # noqa: E402

_ROOT = Path(tempfile.mkdtemp(prefix="studyenglish_test_"))
_failures: list[str] = []


def use_device(name: str) -> None:
    """Point the whole app at a fresh database, as if on another PC."""
    db.close()
    os.environ["STUDYENGLISH_HOME"] = str(_ROOT / name)
    db.connect()
    db.set_meta("device_name", name)


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {actual!r}, expected {expected!r}")
        _failures.append(label)


def live(table: str) -> dict[str, dict]:
    rows = db.connect().execute(
        f"SELECT * FROM {table} WHERE deleted = 0")
    return {r["id"]: dict(r) for r in rows}


# --------------------------------------------------------------------------

def test_sentence_split() -> None:
    print("\n[문장 분리]")
    text = ("Dr. Smith arrived at 9 a.m. He said, \"It works!\" "
            "The value was 3.5 percent.\nA new line here.")
    lines = repo.split_sentences(text)
    check("문장 수", len(lines), 4)
    check("약어로 끊기지 않음", lines[0], "Dr. Smith arrived at 9 a.m.")
    check("따옴표 포함", lines[1], 'He said, "It works!"')
    check("소수점 유지", lines[2], "The value was 3.5 percent.")
    check("줄바꿈 분리", lines[3], "A new line here.")


def test_crud_and_tombstone() -> None:
    print("\n[기본 저장 · 삭제]")
    use_device("crud")
    rid = repo.save_row("expressions", {
        "english": "break the ice", "korean": "어색한 분위기를 풀다",
        "tags": "관용구", "studied_on": "2026-07-20"})
    check("1건 저장", repo.count_rows("expressions"), 1)

    repo.save_row("expressions", {"korean": "서먹함을 깨다"}, row_id=rid)
    check("수정 반영", repo.get_row("expressions", rid)["korean"], "서먹함을 깨다")
    check("영어는 유지", repo.get_row("expressions", rid)["english"], "break the ice")

    repo.soft_delete("expressions", [rid])
    check("목록에서 사라짐", repo.count_rows("expressions"), 0)
    check("묘비는 남음", repo.get_row("expressions", rid)["deleted"], 1)


def test_passage_resplit_keeps_translations() -> None:
    print("\n[지문 다시 나누기]")
    use_device("passage")
    pid = repo.create_passage("t", "One two. Three four. Five six.")
    lines = repo.passage_lines(pid)
    check("3문장", len(lines), 3)

    repo.save_row("passage_lines", {"translation": "셋 넷"}, row_id=lines[1]["id"])
    repo.resplit_passage(pid, "One two. Three four. Five six. Seven eight.")
    after = repo.passage_lines(pid)
    check("4문장으로 늘어남", len(after), 4)
    check("기존 해석 유지", after[1]["translation"], "셋 넷")
    check("새 문장은 비어 있음", after[3]["translation"], "")


def test_merge_two_devices() -> None:
    print("\n[두 기기 병합]")
    # -- device A ------------------------------------------------------
    use_device("A")
    a_only = repo.save_row("expressions", {"english": "A only", "korean": "에이"})
    shared = repo.save_row("expressions", {"english": "shared", "korean": "A가 쓴 뜻"})
    a_export = _ROOT / "from_A.seb"
    sync.export_to_file(a_export)

    # -- device B: start from A's file, then diverge --------------------
    use_device("B")
    sync.import_file(a_export)
    check("B가 A의 항목을 받음", repo.count_rows("expressions"), 2)

    b_only = repo.save_row("expressions", {"english": "B only", "korean": "비"})
    time.sleep(0.01)
    repo.save_row("expressions", {"korean": "B가 나중에 고친 뜻"}, row_id=shared)
    repo.soft_delete("expressions", [a_only])
    b_export = _ROOT / "from_B.seb"
    sync.export_to_file(b_export)

    # -- back on device A ----------------------------------------------
    use_device("A")
    report = sync.import_file(b_export)
    check("추가된 항목", report.total_added, 1)
    check("갱신된 항목", report.total_updated, 2)
    check("삭제 반영", report.deleted_applied, 1)

    rows = live("expressions")
    check("A에 B의 항목이 생김", b_only in rows, True)
    check("나중 수정이 이김", rows[shared]["korean"], "B가 나중에 고친 뜻")
    check("삭제가 전파됨", a_only in rows, False)

    # -- idempotency ----------------------------------------------------
    before = live("expressions")
    again = sync.import_file(b_export)
    check("두 번째 병합은 변화 없음", (again.total_added, again.total_updated), (0, 0))
    check("상태 동일", live("expressions"), before)

    # -- convergence: A merges back into B ------------------------------
    a_final = _ROOT / "from_A_final.seb"
    sync.export_to_file(a_final)
    a_state = live("expressions")

    use_device("B")
    sync.import_file(a_final)
    b_state = live("expressions")
    check("두 기기 상태가 같아짐", b_state, a_state)


def test_merge_order_independent() -> None:
    print("\n[병합 순서 무관]")
    use_device("X")
    x_id = repo.save_row("expressions", {"english": "x", "korean": "엑스"})
    x_file = _ROOT / "x.seb"
    sync.export_to_file(x_file)

    use_device("Y")
    y_id = repo.save_row("expressions", {"english": "y", "korean": "와이"})
    y_file = _ROOT / "y.seb"
    sync.export_to_file(y_file)

    use_device("order1")
    sync.import_file(x_file)
    sync.import_file(y_file)
    first = {r["english"] for r in live("expressions").values()}

    use_device("order2")
    sync.import_file(y_file)
    sync.import_file(x_file)
    second = {r["english"] for r in live("expressions").values()}

    check("순서를 바꿔도 결과 동일", first, second)
    check("두 항목 모두 존재", first, {"x", "y"})


def test_incremental_export() -> None:
    print("\n[변경분만 내보내기]")
    use_device("inc")
    repo.save_row("expressions", {"english": "old", "korean": "옛것"})
    # 경계는 `updated_at >= since` 라서, 같은 밀리초에 저장된 행은 일부러
    # 다시 포함시킨다 (한 번 더 보내는 건 무해하지만, 빠뜨리면 영영 못 옮긴다).
    # 실제 사용에서는 저장과 내보내기 사이에 시간이 흐르므로 테스트도 그렇게 맞춘다.
    time.sleep(0.01)
    mark = db.now_ms() + 1
    time.sleep(0.01)
    repo.save_row("expressions", {"english": "new", "korean": "새것"})

    full = _ROOT / "full.seb"
    partial = _ROOT / "partial.seb"
    full_counts = sync.export_to_file(full)
    partial_counts = sync.export_to_file(partial, since_ms=mark)
    check("전체는 2행", full_counts["expressions"], 2)
    check("변경분은 1행", partial_counts["expressions"], 1)
    check("파일이 더 작음", partial.stat().st_size < full.stat().st_size, True)

    use_device("inc_target")
    sync.import_file(full)
    sync.import_file(partial)
    check("합친 결과는 2건", repo.count_rows("expressions"), 2)

    # 변경분만 받아도 전체를 받은 것과 같은 상태여야 한다.
    use_device("inc_target2")
    sync.import_file(partial)
    sync.import_file(full)
    check("변경분 먼저 받아도 2건", repo.count_rows("expressions"), 2)


def test_passage_lines_merge() -> None:
    print("\n[지문 해석 병합]")
    use_device("P1")
    pid = repo.create_passage("shared", "First one. Second one.")
    lines = repo.passage_lines(pid)
    p1_file = _ROOT / "p1.seb"
    sync.export_to_file(p1_file)

    use_device("P2")
    sync.import_file(p1_file)
    # 다른 기기에서 두 번째 문장만 해석
    repo.save_row("passage_lines", {"translation": "두 번째"}, row_id=lines[1]["id"])
    p2_file = _ROOT / "p2.seb"
    sync.export_to_file(p2_file)

    use_device("P1")
    # 이쪽에서는 첫 번째 문장만 해석
    repo.save_row("passage_lines", {"translation": "첫 번째"}, row_id=lines[0]["id"])
    sync.import_file(p2_file)

    merged = repo.passage_lines(pid)
    check("양쪽 해석이 모두 살아남음",
          [line["translation"] for line in merged], ["첫 번째", "두 번째"])


def test_csv_roundtrip() -> None:
    print("\n[CSV 내보내기 · 가져오기]")
    use_device("csv")
    repo.save_row("expressions", {"english": "keep at it", "korean": "꾸준히 하다",
                                  "tags": "격려"})
    path = _ROOT / "out.csv"
    check("CSV 1행", sync.export_csv("expressions", path), 1)

    use_device("csv_in")
    check("CSV 1행 읽음", sync.import_csv("expressions", path), 1)
    row = next(iter(live("expressions").values()))
    check("한글 보존", row["korean"], "꾸준히 하다")
    check("태그 보존", row["tags"], "격려")


def test_review_flow() -> None:
    print("\n[복습 단계]")
    use_device("review")
    rid = repo.save_row("expressions", {"english": "e", "korean": "ㅇ",
                                        "studied_on": repo.today()})
    check("오늘 항목 조회", len(repo.review_items("expressions",
                                             studied_on=repo.today())), 1)
    repo.mark_reviewed("expressions", rid, correct=True)
    check("맞히면 단계 상승", repo.get_row("expressions", rid)["box"], 1)
    repo.mark_reviewed("expressions", rid, correct=False)
    check("틀리면 0으로", repo.get_row("expressions", rid)["box"], 0)
    check("헷갈리는 항목에 잡힘",
          len(repo.review_items("expressions", only_weak=True)), 1)


def test_bad_file_rejected() -> None:
    print("\n[잘못된 파일]")
    bad = _ROOT / "bad.json"
    bad.write_text('{"format": "something-else"}', encoding="utf-8")
    use_device("bad")
    try:
        sync.import_file(bad)
        check("거부되어야 함", "통과함", "예외 발생")
    except ValueError:
        check("StudyEnglish 파일이 아니면 거부", True, True)


def main() -> int:
    print(f"임시 데이터 위치: {_ROOT}")
    for test in (
        test_sentence_split,
        test_crud_and_tombstone,
        test_passage_resplit_keeps_translations,
        test_merge_two_devices,
        test_merge_order_independent,
        test_incremental_export,
        test_passage_lines_merge,
        test_csv_roundtrip,
        test_review_flow,
        test_bad_file_rejected,
    ):
        test()

    db.close()
    shutil.rmtree(_ROOT, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
