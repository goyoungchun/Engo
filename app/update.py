"""Check GitHub for a newer version, and pull it.

The program is distributed as a git checkout, so "what version am I" is the
commit currently checked out and "is there a newer one" is a comparison
against the default branch on GitHub. That avoids inventing a release
process, and it means updating is `git pull` -- which refuses to run if the
user has local edits, so their own changes cannot be silently destroyed.

Every function here is safe to call from a worker thread and never raises:
callers get a Result describing what happened, including "there is no network"
and "this is not a git checkout", both of which are normal situations rather
than errors.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OWNER = "goyoungchun"
REPO = "Engo"
BRANCH = "main"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
WEB = f"https://github.com/{OWNER}/{REPO}"

PROJECT_DIR = Path(__file__).resolve().parent.parent
TIMEOUT = 8

# state values
UP_TO_DATE = "up_to_date"
BEHIND = "behind"
AHEAD = "ahead"          # local commits not pushed -- nothing to update to
DIVERGED = "diverged"
NO_GIT = "no_git"
OFFLINE = "offline"
ERROR = "error"


@dataclass
class Result:
    state: str
    behind: int = 0
    local: str = ""
    remote: str = ""
    detail: str = ""

    @property
    def update_available(self) -> bool:
        return self.state in (BEHIND, DIVERGED)


def _git(*args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=PROJECT_DIR, capture_output=True, text=True,
            timeout=timeout,
            # Windows would otherwise flash a console window on every call.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def is_checkout() -> bool:
    return (PROJECT_DIR / ".git").exists()


def local_revision() -> str:
    code, out = _git("rev-parse", "HEAD")
    return out if code == 0 else ""


def has_local_changes() -> bool:
    code, out = _git("status", "--porcelain")
    return code == 0 and bool(out.strip())


def _fetch_json(url: str):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": f"{REPO}-updater"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def check() -> Result:
    """Compare the checked-out commit with the branch head on GitHub."""
    if not is_checkout():
        return Result(NO_GIT, detail=WEB)

    local = local_revision()
    if not local:
        return Result(NO_GIT, detail=WEB)

    try:
        head = _fetch_json(f"{API}/commits/{BRANCH}")
        remote = head.get("sha", "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Result(OFFLINE, local=local, detail=str(exc))
    except (ValueError, KeyError) as exc:
        return Result(ERROR, local=local, detail=str(exc))

    if not remote:
        return Result(ERROR, local=local, detail="no sha in response")
    if remote == local:
        return Result(UP_TO_DATE, local=local, remote=remote)

    # How far apart are they? The compare endpoint answers directly, and
    # distinguishes "behind" from "I have unpushed work".
    try:
        cmp = _fetch_json(f"{API}/compare/{local}...{remote}")
        status = cmp.get("status", "")
        behind = int(cmp.get("ahead_by", 0))     # commits remote has that we lack
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Result(OFFLINE, local=local, remote=remote, detail=str(exc))
    except (ValueError, KeyError):
        return Result(BEHIND, local=local, remote=remote)

    if status == "identical":
        return Result(UP_TO_DATE, local=local, remote=remote)
    if status == "behind":
        return Result(AHEAD, local=local, remote=remote)
    if status == "diverged":
        return Result(DIVERGED, behind=behind, local=local, remote=remote)
    return Result(BEHIND, behind=behind, local=local, remote=remote)


def pull() -> tuple[bool, str]:
    """Fast-forward to the latest commit. Never rewrites local work."""
    if not is_checkout():
        return False, "not a git checkout"
    if has_local_changes():
        return False, "local changes"

    code, out = _git("fetch", "origin", BRANCH, timeout=120)
    if code != 0:
        return False, out
    code, out = _git("merge", "--ff-only", f"origin/{BRANCH}", timeout=60)
    return code == 0, out
