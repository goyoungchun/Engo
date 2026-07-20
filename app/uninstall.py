"""Removing Engo from this computer.

Two separate things, deleted in two separate steps because they carry very
different weight:

  * study data -- the database, backups, settings. Irreplaceable.
  * downloaded components -- the .venv and the voice models. Re-downloadable,
    but hundreds of megabytes, so worth offering.

Only what the setup step brought onto the machine is ever touched. If PySide6
was already installed system-wide, we did not download it and we do not
remove it; install-manifest.json is what tells the two apart. The program
folder itself is left for the user to delete -- deleting the folder you are
running from is the kind of clever that goes wrong.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import db, manifest

PROJECT_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = PROJECT_DIR / ".venv"
VOICES_DIR = PROJECT_DIR / "voices"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Target:
    key: str
    path: Path
    ko: str
    en: str
    size: int
    # True when the file is in use by this very process and can only go once
    # we have quit -- the .venv we are running from.
    deferred: bool = False
    # When set, delete exactly these paths -- never the whole directory. A
    # folder can hold files Engo did not put there (an ENGO_HOME the user
    # pointed at a shared folder, a voice model they copied in by hand), and
    # those are not ours to delete.
    paths: list[Path] | None = None
    # With paths set: remove the directory afterwards only if it is empty.
    prune: bool = False
    # Filled in by remove(): what was found in the directory and left alone.
    leftovers: list[Path] = field(default_factory=list)

    def label(self, lang: str) -> str:
        return self.ko if lang == "ko" else self.en


def _size_of(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _running_from_venv() -> bool:
    try:
        return VENV_DIR.resolve() in Path(sys.executable).resolve().parents
    except OSError:
        return False


def data_targets() -> list[Target]:
    """Study data. Everything here is gone for good.

    Only the files Engo itself writes -- the database, its WAL/SHM
    companions, backups, generated speech, the error log. The folder is not
    swept wholesale: ENGO_HOME may point somewhere the user keeps other
    things, and a wrong environment variable must not cost them that folder.
    """
    data_dir = db.default_data_dir()
    if not data_dir.exists():
        return []
    known: list[Path] = []
    for name in ("study.db", "study.db-wal", "study.db-shm", "error.log"):
        item = data_dir / name
        if item.exists():
            known.append(item)
    known += sorted(data_dir.glob("speech*.wav"))
    if (data_dir / "backups").exists():
        known.append(data_dir / "backups")
    if not known:
        return []
    return [Target("data", data_dir,
                   "학습 데이터 (표현·문장·문법·지문·설정·백업)",
                   "Study data (expressions, sentences, grammar, settings, backups)",
                   sum(_size_of(p) for p in known), paths=known, prune=True)]


def _known_voice_files() -> list[Path]:
    """Voice files Engo could have downloaded -- and only those.

    Matched against the catalogue by filename, because the voices folder can
    also hold a model the user copied in themselves, which no download of
    ours produced and no uninstall of ours should take away.
    """
    try:
        from . import tts
    except Exception:
        return []                       # cannot tell ours apart: keep all
    stems = {tts.Voice("", "female", model, quality, "", "").stem
             for model, quality, _mb in tts.CATALOGUE}
    stems |= {voice.stem for voice in tts.FACTORY_SLOTS.values()}
    try:
        return [item for item in VOICES_DIR.iterdir()
                if any(item.name.startswith(stem + ".") for stem in stems)]
    except OSError:
        return []


def component_targets() -> list[Target]:
    """Things the setup step downloaded because they were not here."""
    targets: list[Target] = []

    if VOICES_DIR.exists():
        files = _known_voice_files()
        if files:
            targets.append(Target(
                "voices", VOICES_DIR,
                "내려받은 읽어주기 음성 파일", "Downloaded speech voices",
                sum(_size_of(p) for p in files), paths=files, prune=True))

    # Only a venv the setup step created. One the user built themselves is
    # theirs -- it existed before us, whatever we later pip-installed into
    # it. When the manifest is missing or unreadable this errs the same way:
    # toward keeping. Packages that were already on this machine live in the
    # system Python, which we never installed into and never remove --
    # kept_packages() is what names them for the user.
    if VENV_DIR.exists() and manifest.venv_is_ours():
        targets.append(Target(
            "venv", VENV_DIR,
            "설치할 때 내려받은 라이브러리 (.venv)",
            "Libraries downloaded by setup (.venv)",
            _size_of(VENV_DIR), deferred=_running_from_venv()))

    return targets


def venv_kept() -> bool:
    """A .venv exists that we did not create, so removal leaves it alone."""
    return VENV_DIR.exists() and not manifest.venv_is_ours()


def kept_packages() -> list[str]:
    """What was already on the machine, and so will not be removed."""
    return manifest.packages_preexisting()


def remove_autostart() -> None:
    try:
        from .main import set_autostart
        set_autostart(False)
    except Exception:
        pass


def remove(targets: list[Target]) -> tuple[list[Target], list[tuple[Target, str]]]:
    """Delete now what can be deleted now. Returns (done, failed)."""
    done: list[Target] = []
    failed: list[tuple[Target, str]] = []

    for target in targets:
        if target.deferred:
            done.append(target)          # handed to the cleanup script instead
            continue
        try:
            if target.paths is None:
                if target.path.is_file():
                    target.path.unlink()
                else:
                    shutil.rmtree(target.path)
            else:
                for item in target.paths:
                    if item.is_dir():
                        shutil.rmtree(item)
                    elif item.exists():
                        item.unlink()
                if target.prune and target.path.is_dir():
                    target.leftovers = sorted(target.path.iterdir())
                    if not target.leftovers:
                        target.path.rmdir()
            done.append(target)
        except OSError as error:
            failed.append((target, str(error)))
    return done, failed


def schedule_deferred(targets: list[Target]) -> bool:
    """Queue a cleanup that runs after we quit, for files we hold open.

    Windows will not delete the interpreter a running process was started
    from, so a small batch file waits for this PID to disappear and then
    removes the folder -- and finally itself.
    """
    pending = [t for t in targets if t.deferred]
    if not pending or os.name != "nt":
        return False

    script = PROJECT_DIR / "engo-cleanup.bat"
    lines = [
        "@echo off",
        "rem Written by Engo's uninstall step. Removes itself when done.",
        ":wait",
        f'tasklist /fi "PID eq {os.getpid()}" 2>nul | find "{os.getpid()}" >nul',
        "if not errorlevel 1 (",
        "    timeout /t 1 /nobreak >nul",
        "    goto wait",
        ")",
    ]
    lines += [f'rmdir /s /q "{t.path}"' for t in pending]
    lines += ['del "%~f0"']

    try:
        script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(script)], cwd=str(PROJECT_DIR),
                         creationflags=_NO_WINDOW)
    except OSError:
        return False
    return True


def close_everything() -> None:
    """Release the database and speech files before deleting the data dir."""
    try:
        from . import tts
        tts.shutdown()
    except Exception:
        pass
    try:
        # Seal rather than close: shutting down still writes (sticky notes
        # remember where they were), and those writes must not recreate the
        # folder we are about to delete.
        db.seal()
    except Exception:
        pass


def drop_manifest() -> None:
    try:
        manifest.MANIFEST_PATH.unlink()
    except OSError:
        pass


def open_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))          # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def human(size: int) -> str:
    if size >= 1 << 30:
        return f"{size / (1 << 30):.1f} GB"
    if size >= 1 << 20:
        return f"{size / (1 << 20):.0f} MB"
    if size >= 1 << 10:
        return f"{size / (1 << 10):.0f} KB"
    return f"{size} B"
