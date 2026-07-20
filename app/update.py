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
import re
import shutil
import subprocess
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
KEEP = {".venv", "venv", "voices", ".git", "__pycache__", "backups",
        ".update-backup", ".update-staging",
        # Describes this machine's install, not the release. Replacing it
        # would make uninstall forget what setup downloaded.
        "install-manifest.json", "setup.log"}

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
    """Swap a release zip into the program folder.

    Built to survive a failure at any point:
      * the zip is validated for an Engo layout before anything moves
      * staging lives INSIDE the program folder, so every move is a
        same-volume rename -- fast and atomic per entry
      * old items are moved wholesale to .update-backup (not merge-copied),
        so files a release deleted do not linger and shadow new code
      * any OSError mid-swap rolls the moved items back before returning
    """
    staging = PROJECT_DIR / ".update-staging"
    backup = PROJECT_DIR / ".update-backup"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)

    try:
        staging.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(staging)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return False, str(exc)

    roots = [p for p in staging.iterdir() if p.is_dir()]
    if len(roots) != 1 or not (roots[0] / "app" / "main.py").exists():
        shutil.rmtree(staging, ignore_errors=True)
        return False, "archive does not look like Engo"
    root = roots[0]

    items = [p for p in root.iterdir() if p.name not in KEEP]
    moved_out: list[str] = []       # names now sitting in backup/
    moved_in: list[str] = []        # names now installed from the archive
    try:
        backup.mkdir(parents=True)
        for item in items:          # phase A: old versions out of the way
            target = PROJECT_DIR / item.name
            if target.exists():
                target.replace(backup / item.name) if target.is_file() \
                    else target.rename(backup / item.name)
                moved_out.append(item.name)
        for item in items:          # phase B: new versions in
            item.rename(PROJECT_DIR / item.name)
            moved_in.append(item.name)
    except OSError as exc:
        # Roll back: drop what came in, restore what went out.
        for name in moved_in:
            path = PROJECT_DIR / name
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() \
                else path.unlink(missing_ok=True)
        for name in moved_out:
            try:
                (backup / name).rename(PROJECT_DIR / name)
            except OSError:
                pass                # best effort; the backup dir remains
        shutil.rmtree(staging, ignore_errors=True)
        return False, str(exc)

    shutil.rmtree(staging, ignore_errors=True)
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
