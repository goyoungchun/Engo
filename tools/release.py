"""Publish a release, when a release is wanted.

Run only on request -- pushing to main is deliberately not a release. The
update check in the program reads GitHub *Releases*, not commits, so work
sits unpublished until someone decides a version is worth shipping.

    python tools/release.py -n "요약 1" -n "요약 2" -n "요약 3"
    python tools/release.py 1.1.0 -n "..."     # an explicit version
    python tools/release.py --dry-run          # say what would happen

Notes are three Korean lines describing what changed, because that is what
the program shows the user before they agree to install. Without -n the
commit subjects since the last tag are offered as a starting point, and you
are asked to confirm them.

Bumps __version__, commits, tags, pushes, creates the release, then re-reads
the API to confirm an older copy would now be offered it. Needs the `gh` CLI.
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "app" / "__init__.py"
API = "https://api.github.com/repos/goyoungchun/Engo/releases/latest"


def run(*args: str, check: bool = True) -> str:
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode:
        raise SystemExit(f"실패: {' '.join(args)}\n{proc.stdout}{proc.stderr}")
    return (proc.stdout + proc.stderr).strip()


def current_version() -> str:
    text = INIT.read_text(encoding="utf-8-sig")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("app/__init__.py 에서 __version__ 을 찾지 못했습니다")
    return match.group(1)


def bump(version: str) -> str:
    """1.0.1 -> 1.0.2. The default step, unless a version is given."""
    parts = [int(n) for n in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    parts[2] += 1
    return ".".join(str(n) for n in parts)


def write_version(version: str) -> None:
    text = INIT.read_text(encoding="utf-8-sig")
    text = re.sub(r'(__version__\s*=\s*")[^"]+(")', rf'\g<1>{version}\g<2>',
                  text, count=1)
    INIT.write_text(text, encoding="utf-8-sig")


def commits_since(previous: str) -> list[str]:
    """Commit subjects since the last tag -- a draft, not the notes."""
    tag = f"v{previous}"
    code = subprocess.run(["git", "rev-parse", tag], cwd=ROOT,
                          capture_output=True).returncode
    span = f"{tag}..HEAD" if code == 0 else "HEAD"
    out = run("git", "log", "--no-merges", "--format=%s", span)
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    argv = sys.argv[1:]
    given_notes: list[str] = []
    args: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in ("-n", "--note") and index + 1 < len(argv):
            given_notes.append(argv[index + 1])
            index += 2
            continue
        if not item.startswith("--"):
            args.append(item)
        index += 1
    dry = "--dry-run" in argv

    previous = current_version()
    version = args[0] if args else bump(previous)
    tag = f"v{version}"

    print(f"  현재 버전 : {previous}")
    print(f"  새 버전   : {version}  ({tag})")

    if run("git", "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise SystemExit("main 브랜치에서만 릴리스할 수 있습니다")
    dirty = run("git", "status", "--porcelain")
    if dirty:
        raise SystemExit(f"커밋되지 않은 변경이 있습니다:\n{dirty}")
    if run("git", "tag", "-l", tag):
        raise SystemExit(f"{tag} 태그가 이미 있습니다")

    if given_notes:
        lines = given_notes
    else:
        # A draft from the commit log. These are English commit subjects
        # written for the repository, not the three Korean lines the user
        # reads in the update dialog, so they need replacing before shipping.
        lines = commits_since(previous)
        print("\n  -n 이 없어 커밋 제목을 초안으로 씁니다. "
              "실제 릴리스에는 한글 3줄 요약을 -n 으로 넘기세요:")
    notes = "\n".join(f"- {line.lstrip('- ')}" for line in lines) or "- 개선 및 수정"
    print(f"  릴리스 노트:\n{notes}")
    if len(lines) != 3:
        print(f"  참고: {len(lines)}줄입니다 (3줄 요약을 권장)")

    if dry:
        print("\n  (--dry-run: 아무것도 하지 않았습니다)")
        return 0

    if not given_notes:
        answer = input("\n  이 내용으로 발행할까요? [y/N] ").strip().lower()
        if answer != "y":
            print("  취소했습니다.")
            return 1

    write_version(version)
    run("git", "add", str(INIT))
    run("git", "commit", "-m", f"Release {tag}")
    run("git", "tag", "-a", tag, "-m", f"Engo {tag}")
    run("git", "push", "origin", "main")
    run("git", "push", "origin", tag)
    run("gh", "release", "create", tag, "--title", f"Engo {tag}",
        "--notes", notes)
    print(f"  릴리스 발행 완료: {tag}")

    # The point of the whole exercise: an older copy must now be offered it.
    with urllib.request.urlopen(API, timeout=15) as response:
        latest = json.loads(response.read().decode("utf-8")).get("tag_name")
    if latest == tag:
        print(f"  확인: 업데이트 확인 API 가 {latest} 를 돌려줍니다 — "
              f"이전 버전 사용자에게 업데이트가 보입니다")
        return 0
    print(f"  경고: API 가 아직 {latest} 를 돌려줍니다 (반영이 늦을 수 있음)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
