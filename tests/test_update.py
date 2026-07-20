"""Update checker tests.

The state machine is tested against canned GitHub responses rather than the
live API: the point is that each answer maps to the right state, and a test
that depends on what is currently on the branch would report a different
result tomorrow. One real request at the end confirms the network path works.

Run:  .venv\\Scripts\\python.exe tests\\test_update.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import update  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


LOCAL = "a" * 40
REMOTE = "b" * 40


def with_responses(head, compare, local=LOCAL, checkout=True):
    """Run update.check() against canned API replies."""
    originals = (update._fetch_json, update.local_revision, update.is_checkout)

    def fake_fetch(url: str):
        if "/commits/" in url:
            if isinstance(head, Exception):
                raise head
            return head
        if isinstance(compare, Exception):
            raise compare
        return compare

    update._fetch_json = fake_fetch
    update.local_revision = lambda: local
    update.is_checkout = lambda: checkout
    try:
        return update.check()
    finally:
        (update._fetch_json, update.local_revision,
         update.is_checkout) = originals


def main() -> int:
    print("[상태 판정]")

    result = with_responses({"sha": LOCAL}, None)
    check("같은 커밋 → 최신", result.state == update.UP_TO_DATE, result.state)
    check("최신일 때 업데이트 표시 없음", not result.update_available)

    result = with_responses({"sha": REMOTE},
                            {"status": "ahead", "ahead_by": 3})
    check("원격이 앞서면 → 뒤처짐", result.state == update.BEHIND, result.state)
    check("뒤처진 커밋 수", result.behind == 3, str(result.behind))
    check("업데이트 표시 켜짐", result.update_available)

    result = with_responses({"sha": REMOTE},
                            {"status": "behind", "ahead_by": 0})
    check("내가 앞서면 → 안 올린 커밋", result.state == update.AHEAD, result.state)
    check("이 경우 업데이트 표시 없음", not result.update_available)

    result = with_responses({"sha": REMOTE},
                            {"status": "diverged", "ahead_by": 2})
    check("갈라진 경우 → diverged", result.state == update.DIVERGED, result.state)
    check("갈라지면 사용자에게 알림", result.update_available)

    print("\n[문제 상황]")
    result = with_responses(OSError("no route to host"), None)
    check("네트워크 불가 → offline", result.state == update.OFFLINE, result.state)
    check("offline은 업데이트 표시 안 함", not result.update_available)

    result = with_responses({"sha": REMOTE}, OSError("dropped"))
    check("비교 중 끊김 → offline", result.state == update.OFFLINE, result.state)

    result = with_responses({}, None)
    check("sha 없는 응답 → error", result.state == update.ERROR, result.state)

    result = with_responses({"sha": REMOTE}, None, checkout=False)
    check("git 폴더 아님 → no_git", result.state == update.NO_GIT, result.state)
    check("no_git이면 링크용 주소를 준다",
          result.detail.startswith("https://"), result.detail)

    print("\n[안전장치]")
    check("저장소 주소가 Engo를 가리킴",
          update.WEB.endswith("/goyoungchun/Engo"), update.WEB)
    dirty = update.has_local_changes()
    print(f"  (지금 작업 폴더 수정 상태: {dirty})")
    if dirty:
        ok, message = update.pull()
        check("고친 파일이 있으면 업데이트를 거부", not ok, message)
    else:
        print("  -- 작업 폴더가 깨끗해 거부 경로는 건너뜀")

    print("\n[실제 GitHub 조회]")
    live = update.check()
    check("실제 응답이 알려진 상태 중 하나",
          live.state in (update.UP_TO_DATE, update.BEHIND, update.AHEAD,
                         update.DIVERGED, update.OFFLINE, update.NO_GIT,
                         update.ERROR),
          live.state)
    if live.state == update.OFFLINE:
        print("  (인터넷이 없어 실제 비교는 건너뜁니다)")
    else:
        check("원격 커밋 해시를 받아옴", len(live.remote) == 40, live.remote[:12])

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 업데이트 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
