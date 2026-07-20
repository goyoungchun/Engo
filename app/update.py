"""Check GitHub for a newer release, download it, and install it.

Written for someone who downloaded the program, not for someone developing
it: the user sees version numbers, never commits or branches, and updating
does not require git to be installed. The published release archive is
fetched and unpacked over the program folder.

A git checkout is still handled -- it fast-forwards instead of unpacking a
zip, which keeps a developer's clone intact -- but that is an implementation
detail the interface never mentions.

Nothing here raises: callers get a Result, including for "there is no
network", which is a normal situation rather than an error.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__

OWNER = "goyoungchun"
REPO = "Engo"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
WEB = f"https://github.com/{OWNER}/{REPO}"
RELEASES = f"{WEB}/releases"

PROJECT_DIR = Path(__file__).resolve().parent.parent
TIMEOUT = 10

# Folders the update must never touch: the user's voices are hundreds of MB
# and are not in the archive, and the virtualenv is theirs.
KEEP = {".venv", "venv", "voices", ".git", "__pycache__", "backups"}

# state values
UP_TO_DATE = "up_to_date"
AVAILABLE = "available"
OFFLINE = "offline"
ERROR = "error"


@dataclass
class Result:
    state: str
    current: str = __version__
    latest: str = ""
    notes: str = ""
    detail: str = ""

    @property
    def update_available(self) -> bool:
        return self.state == AVAILABLE


def _parse(version: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3). Unparseable versions sort lowest."""
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in numbers[:4]) or (0,)


def _fetch_json(url: str):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": f"{REPO}-updater"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def check() -> Result:
    """Is there a newer published release than the version running?"""
    try:
        release = _fetch_json(f"{API}/releases/latest")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # No releases published yet -- nothing to offer, not a failure.
            return Result(UP_TO_DATE)
        return Result(ERROR, detail=str(exc))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Result(OFFLINE, detail=str(exc))
    except ValueError as exc:
        return Result(ERROR, detail=str(exc))

    latest = str(release.get("tag_name") or "").strip()
    if not latest:
        return Result(UP_TO_DATE)

    if _parse(latest) > _parse(__version__):
        return Result(AVAILABLE, latest=latest,
                      notes=str(release.get("body") or "").strip())
    return Result(UP_TO_DATE, latest=latest)


# --------------------------------------------------------------------------
# installing
# --------------------------------------------------------------------------

def _is_git_checkout() -> bool:
    return (PROJECT_DIR / ".git").exists()


def _git(*args: str, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=PROJECT_DIR, capture_output=True, text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def has_local_changes() -> bool:
    if not _is_git_checkout():
        return False
    code, out = _git("status", "--porcelain", timeout=30)
    return code == 0 and bool(out.strip())


def _download_archive(tag: str, progress=None) -> bytes:
    url = f"{WEB}/archive/refs/tags/{tag}.zip"
    request = urllib.request.Request(url, headers={"User-Agent": REPO})
    buffer = io.BytesIO()
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            buffer.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    return buffer.getvalue()


def _install_archive(data: bytes) -> tuple[bool, str]:
    """Unpack a release zip over the program folder.

    The archive is checked for a recognisable Engo layout before anything is
    replaced, and the files it will overwrite are copied aside first, so a
    corrupt download cannot leave a half-updated program behind.
    """
    with tempfile.TemporaryDirectory(prefix="engo_update_") as tmp:
        staging = Path(tmp)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(staging)
        except zipfile.BadZipFile as exc:
            return False, str(exc)

        roots = [p for p in staging.iterdir() if p.is_dir()]
        if len(roots) != 1:
            return False, "unexpected archive layout"
        root = roots[0]
        if not (root / "app" / "main.py").exists():
            return False, "archive does not look like Engo"

        backup = PROJECT_DIR / ".update-backup"
        shutil.rmtree(backup, ignore_errors=True)
        backup.mkdir(parents=True, exist_ok=True)

        try:
            for item in root.iterdir():
                if item.name in KEEP:
                    continue
                target = PROJECT_DIR / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.copytree(target, backup / item.name,
                                        dirs_exist_ok=True)
                    else:
                        shutil.copy2(target, backup / item.name)
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        except OSError as exc:
            return False, str(exc)

    return True, ""


def install(progress=None) -> tuple[bool, str]:
    """Update to the latest release. Returns (ok, message)."""
    if _is_git_checkout():
        if has_local_changes():
            return False, "local changes"
        code, out = _git("fetch", "origin", "--tags")
        if code != 0:
            return False, out
        code, out = _git("merge", "--ff-only", "origin/main")
        return code == 0, out

    result = check()
    if result.state == OFFLINE:
        return False, result.detail
    if not result.update_available:
        return True, ""
    try:
        data = _download_archive(result.latest, progress)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)
    return _install_archive(data)
