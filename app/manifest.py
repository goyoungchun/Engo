"""A record of what the setup step actually installed.

Uninstalling must remove what Engo brought onto the machine and nothing else.
The only way to know the difference is to write it down at install time: if
PySide6 was already on this computer we did not download it, and we must not
delete it -- something else may depend on it.

Deliberately stdlib-only and free of any `app` imports beyond the package
itself, because bootstrap.py runs this before a single dependency exists.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_DIR / "install-manifest.json"

VERSION = 1


def load() -> dict:
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    data["manifest_version"] = VERSION
    try:
        MANIFEST_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass          # a missing manifest degrades uninstall, never blocks it


def record_setup(*, python: str, venv_created: bool,
                 installed: list[str], preexisting: list[str]) -> None:
    """Called by bootstrap.py once setup finishes."""
    data = load()
    data.update({
        "installed_at": data.get("installed_at") or int(time.time()),
        "updated_at": int(time.time()),
        "python": python,
        # Only true when the setup step created it. A .venv the user made
        # themselves is theirs, and uninstall leaves it alone.
        "venv_created_by_setup": bool(venv_created)
                                 or bool(data.get("venv_created_by_setup")),
        "packages_installed": sorted(set(data.get("packages_installed", []))
                                     | set(installed)),
        "packages_preexisting": sorted(set(preexisting)),
    })
    save(data)


def venv_is_ours() -> bool:
    return bool(load().get("venv_created_by_setup"))


def packages_installed() -> list[str]:
    return list(load().get("packages_installed", []))


def packages_preexisting() -> list[str]:
    return list(load().get("packages_preexisting", []))
