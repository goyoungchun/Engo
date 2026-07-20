"""Publish a release, so other machines can actually receive the update.

The update check in the program reads GitHub *Releases*, not commits. Pushing
to main therefore changes nothing for anyone who downloaded the program --
their copy keeps being told it is up to date, which is exactly what happened
between v1.0.0 and v1.0.1. Publishing is what makes an update real, and it is
four steps that must all happen, so it lives here as one command instead of
in someone's memory.

    python tools/release.py              # 1.0.1 -> 1.0.2
    python tools/release.py 1.1.0        # an explicit version
    python tools/release.py --dry-run    # say what would happen

It bumps __version__, commits that, tags, pushes, creates the GitHub release,
and then re-reads the API to confirm an older copy would now be offered the
update. Needs the `gh` CLI, already used for this repository.
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


def notes_since(previous: str) -> str:
    """Commit subjects since the last tag, as the release body."""
    tag = f"v{previous}"
    code = subprocess.run(["git", "rev-parse", tag], cwd=ROOT,
                          capture_output=True).returncode
    span = f"{tag}..HEAD" if code == 0 else "HEAD"
    lines = run("git", "log", "--no-merges", "--format=- %s", span).splitlines()
    return "\n".join(lines) or "- 개선 및 수정"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv

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

    notes = notes_since(previous)
    print(f"  릴리스 노트:\n{notes}")

    if dry:
        print("\n  (--dry-run: 아무것도 하지 않았습니다)")
        return 0

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
