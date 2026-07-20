"""Update checker and installer.

The state machine runs against canned GitHub replies -- a test that depended
on what is published today would report something different tomorrow. The
archive install, though, runs for real against a downloaded release zip,
because the parts that break there (a wrong layout, a file that must not be
replaced) cannot be exercised by a stub.

Run:  .venv\\Scripts\\python.exe tests\\test_update.py
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import urllib.error
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import __version__, update  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def with_release(payload):
    """Run update.check() against a canned /releases/latest reply."""
    original = update._fetch_json

    def fake(url: str):
        if isinstance(payload, Exception):
            raise payload
        return payload

    update._fetch_json = fake
    try:
        return update.check()
    finally:
        update._fetch_json = original


def make_archive(root_name: str, files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in files.items():
            archive.writestr(f"{root_name}/{path}", text)
    return buffer.getvalue()


def main() -> int:
    print(f"실행 중인 버전: {__version__}")

    print("\n[버전 비교]")
    result = with_release({"tag_name": f"v{__version__}"})
    check("같은 버전 → 최신", result.state == update.UP_TO_DATE, result.state)
    check("최신이면 업데이트 표시 없음", not result.update_available)

    result = with_release({"tag_name": "v99.0.0", "body": "새 기능"})
    check("더 높은 버전 → 업데이트 있음", result.state == update.AVAILABLE,
          result.state)
    check("새 버전 번호를 알려준다", result.latest == "v99.0.0", result.latest)
    check("변경 내용을 담아온다", result.notes == "새 기능", result.notes)

    result = with_release({"tag_name": "v0.0.1"})
    check("더 낮은 버전은 무시", result.state == update.UP_TO_DATE, result.state)

    check("버전 파싱", update._parse("v1.2.3") == (1, 2, 3),
          str(update._parse("v1.2.3")))
    check("자리수가 달라도 비교된다",
          update._parse("v1.10.0") > update._parse("v1.9.0"))

    print("\n[문제 상황]")
    result = with_release(OSError("no route to host"))
    check("네트워크 불가 → offline", result.state == update.OFFLINE, result.state)
    check("offline은 업데이트 표시 안 함", not result.update_available)

    result = with_release(urllib.error.HTTPError(
        "u", 404, "Not Found", {}, None))
    check("릴리스가 아직 없으면 조용히 최신 취급",
          result.state == update.UP_TO_DATE, result.state)

    result = with_release({})
    check("태그 없는 응답도 최신 취급", result.state == update.UP_TO_DATE,
          result.state)

    print("\n[사용자에게 보일 문구에 개발 용어가 없는지]")
    from app import i18n
    for key in ("update_latest", "update_available", "update_offline",
                "update_error", "update_dirty", "update_done_body"):
        for text in i18n.S[key]:
            lowered = text.lower()
            bad = [w for w in ("commit", "커밋", "branch", "브랜치", "git",
                               "sha", "diverge") if w in lowered]
            check(f"{key}: 개발 용어 없음", not bad, f"({bad})" if bad else "")

    print("\n[릴리스 압축파일 설치]")
    sandbox = Path(tempfile.mkdtemp(prefix="engo_inst_"))
    real_dir = update.PROJECT_DIR
    update.PROJECT_DIR = sandbox
    try:
        # a program folder with user data that must survive
        (sandbox / "app").mkdir()
        (sandbox / "app" / "main.py").write_text("old", encoding="utf-8")
        (sandbox / "voices").mkdir()
        (sandbox / "voices" / "big.onnx").write_text("keep me", encoding="utf-8")
        (sandbox / ".venv").mkdir()
        (sandbox / ".venv" / "marker").write_text("keep me", encoding="utf-8")
        (sandbox / "study.db").write_text("user data", encoding="utf-8")

        good = make_archive("Engo-1.1.0", {
            "app/main.py": "new",
            "app/extra.py": "added",
            "README.md": "docs",
        })
        ok, message = update._install_archive(good)
        check("설치 성공", ok, message)
        check("파일이 새 내용으로 바뀐다",
              (sandbox / "app" / "main.py").read_text(encoding="utf-8") == "new")
        check("새로 생긴 파일도 들어온다", (sandbox / "app" / "extra.py").exists())
        check("음성 폴더는 건드리지 않는다",
              (sandbox / "voices" / "big.onnx").read_text(encoding="utf-8") == "keep me")
        check("가상환경은 건드리지 않는다", (sandbox / ".venv" / "marker").exists())
        check("압축파일에 없던 사용자 파일은 남는다", (sandbox / "study.db").exists())
        check("바꾸기 전 파일을 백업해둔다",
              (update.PROJECT_DIR / ".update-backup" / "app" / "main.py")
              .read_text(encoding="utf-8") == "old")

        print("\n[잘못된 압축파일은 아무것도 바꾸지 않는다]")
        before = (sandbox / "app" / "main.py").read_text(encoding="utf-8")
        wrong = make_archive("SomethingElse-1.0", {"readme.txt": "not engo"})
        ok, message = update._install_archive(wrong)
        check("Engo가 아니면 거부", not ok, message)
        check("파일이 그대로다",
              (sandbox / "app" / "main.py").read_text(encoding="utf-8") == before)

        ok, message = update._install_archive(b"this is not a zip")
        check("깨진 파일도 예외 없이 거부", not ok, message[:40])
        check("파일이 여전히 그대로다",
              (sandbox / "app" / "main.py").read_text(encoding="utf-8") == before)
    finally:
        update.PROJECT_DIR = real_dir
        shutil.rmtree(sandbox, ignore_errors=True)

    print("\n[실제 GitHub 조회]")
    live = update.check()
    check("응답이 알려진 상태 중 하나",
          live.state in (update.UP_TO_DATE, update.AVAILABLE, update.OFFLINE,
                         update.ERROR), live.state)
    if live.state != update.OFFLINE:
        # Not "or True". A published release older than the version running
        # means the bump happened and the release did not, and every copy
        # out there is being told it is up to date.
        check("배포된 릴리스가 실행 중인 버전보다 뒤처지지 않는다",
              bool(live.latest)
              and update._parse(live.latest) >= update._parse(__version__),
              f"(배포={live.latest or '없음'}, 실행={__version__})")

    print("\n[아직 배포하지 않은 커밋]")
    # Informational, not a failure: releases go out when they are asked for,
    # so commits sitting unreleased on main are the normal state. What this
    # answers is "would anyone receive what I just wrote?" -- and the answer
    # being no is a decision, not a bug.
    if not (Path(__file__).resolve().parent.parent / ".git").exists():
        print("  건너뜀: git 체크아웃이 아닙니다")
    else:
        import subprocess
        root = Path(__file__).resolve().parent.parent

        def git(*args):
            done = subprocess.run(["git", *args], cwd=root, text=True,
                                  capture_output=True)
            return done.returncode, (done.stdout or "").strip()

        code, tag = git("describe", "--tags", "--abbrev=0")
        if code:
            print("  건너뜀: 태그가 없습니다 (git fetch --tags)")
        else:
            _, behind = git("log", "--oneline", f"{tag}..HEAD")
            pending = [line for line in behind.splitlines() if line.strip()]
            if pending:
                print(f"  안내: {tag} 이후 {len(pending)}건이 아직 배포되지 "
                      f"않았습니다. 배포하려면 python tools/release.py")
            else:
                print(f"  {tag} 까지 모두 배포되었습니다")

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 업데이트 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
