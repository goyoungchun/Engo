"""Set up and start Engo in one step.

Engo.bat runs this with whatever Python it can find. Everything here is
stdlib-only on purpose -- it has to work on a machine where not one of the
program's dependencies is installed yet, which rules out PySide6 for the
window and leaves tkinter.

What it does:

  1. Surveys the machine: which dependencies are already here, which are not.
  2. If nothing is missing, launches straight away -- no dialog, no delay.
     That is the normal case from the second run onwards.
  3. Otherwise shows what is already installed and what has to be downloaded,
     with sizes, and waits for the user to agree before touching anything.
  4. Installs only the missing pieces into a local .venv, and writes down
     what it installed so the uninstall step can remove exactly that much.

Nothing is ever installed into the system Python. The venv inherits packages
that are already on the machine (--system-site-packages), so a dependency the
user already has is reused rather than downloaded a second time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_DIR = HERE / ".venv"
LOG_PATH = HERE / "setup.log"

MIN_PYTHON = (3, 10)

# Windows: no console window for any helper process we spawn.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------
# what the program needs

class Requirement:
    """One dependency, and how to tell whether it is already here."""

    def __init__(self, spec: str, module: str, ko: str, en: str, mb: int):
        self.spec = spec          # what pip is asked for
        self.module = module      # what a working install can import
        self.ko = ko
        self.en = en
        self.mb = mb              # download size including its own deps

    def label(self, lang: str) -> str:
        return self.ko if lang == "ko" else self.en


REQUIREMENTS = [
    Requirement("PySide6-Essentials>=6.7", "PySide6",
                "화면 라이브러리 (PySide6)", "Window toolkit (PySide6)", 85),
    Requirement("piper-tts>=1.5", "piper",
                "읽어주기 엔진 (Piper TTS)", "Speech engine (Piper TTS)", 240),
]


# --------------------------------------------------------------------------
# text

def _language() -> str:
    for name in ("LANG", "LC_ALL"):
        if os.environ.get(name, "").lower().startswith("ko"):
            return "ko"
    try:
        import locale
        if (locale.getdefaultlocale()[0] or "").lower().startswith("ko"):
            return "ko"
    except Exception:
        pass
    return "ko" if sys.getdefaultencoding() and os.name == "nt" else "en"


TEXT = {
    "title": ("Engo 설치", "Engo setup"),
    "intro": ("Engo를 실행하려면 아래 항목이 필요합니다.",
              "Engo needs the following to run."),
    "have": ("이미 설치되어 있습니다 — 내려받지 않습니다",
             "Already on this computer — will not be downloaded"),
    "need": ("이 컴퓨터에 없어서 새로 내려받습니다",
             "Missing from this computer — will be downloaded"),
    "venv": ("가상환경(.venv) 만들기",
             "Create the virtual environment (.venv)"),
    "total": ("내려받을 용량 약 {mb} MB", "About {mb} MB to download"),
    "where": ("모두 이 폴더 안에만 설치됩니다:\n{path}",
              "Everything is installed inside this folder only:\n{path}"),
    "note": ("시스템에 설치된 Python은 건드리지 않습니다.",
             "Your system Python is left untouched."),
    "go": ("설치하고 실행", "Install and run"),
    "cancel": ("취소", "Cancel"),
    "working": ("설치하는 중입니다. 처음 한 번만 걸립니다…",
                "Installing. This happens only once…"),
    "step_venv": ("가상환경을 만드는 중…", "Creating the virtual environment…"),
    "step_pip": ("{name} 내려받는 중…", "Downloading {name}…"),
    "done": ("설치가 끝났습니다. Engo를 시작합니다.",
             "Setup finished. Starting Engo."),
    "failed": ("설치에 실패했습니다.\n\n{err}\n\n자세한 내용: {log}",
               "Setup failed.\n\n{err}\n\nDetails: {log}"),
    "deep_path": (
        "폴더 경로가 너무 깁니다.\n\n{path}\n\n"
        "Windows 의 경로 길이 제한(260자) 때문에, 여기에 설치하면 화면 "
        "라이브러리를 푸는 도중 실패합니다.\n\n"
        "폴더를 C:\\Engo 처럼 짧은 경로로 옮긴 뒤 다시 실행하세요.",
        "The folder path is too long.\n\n{path}\n\n"
        "Windows limits paths to 260 characters, and unpacking the window "
        "toolkit here would fail partway through.\n\n"
        "Move the folder somewhere shorter, such as C:\\Engo, and run it "
        "again."),
    "old_python": (
        "Python {have} 이 설치되어 있는데 Engo는 {need} 이상이 필요합니다.\n\n"
        "python.org 에서 최신 Python을 설치한 뒤 다시 실행하세요.",
        "Python {have} is installed but Engo needs {need} or newer.\n\n"
        "Install a newer Python from python.org and run this again."),
    "close": ("닫기", "Close"),
}


def t(key: str, lang: str, **kw) -> str:
    ko, en = TEXT[key]
    return (ko if lang == "ko" else en).format(**kw)


# --------------------------------------------------------------------------
# survey

# PySide6 ships Qt's own tree, and its deepest bundled file sits about this
# many characters below the folder we install into. Measured, not guessed:
# .venv\Lib\site-packages\PySide6\qml\Qt\labs\assetdownloader\objects-Debug\...
DEEPEST_SUFFIX = 140
MAX_PATH = 260


def _long_paths_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except Exception:
        return False


def path_too_deep() -> bool:
    """Would installing here overrun Windows' 260-character path limit?

    Worth answering before the download rather than after: pip fails partway
    through unpacking with a bare WinError 206, which tells the user nothing.
    """
    if os.name != "nt" or _long_paths_enabled():
        return False
    return len(str(HERE)) + DEEPEST_SUFFIX > MAX_PATH


def _venv_python(windowless: bool = False) -> Path | None:
    name = "pythonw.exe" if windowless else "python.exe"
    for candidate in (VENV_DIR / "Scripts" / name, VENV_DIR / "bin" / name):
        if candidate.exists():
            return candidate
    return None


def _base_python() -> str:
    """The interpreter to build the venv from -- never the venv itself."""
    current = Path(sys.executable).resolve()
    venv = _venv_python()
    if venv is None or current != venv.resolve():
        return sys.executable
    # We were started by the venv but it is incomplete; fall back to its base.
    cfg = VENV_DIR / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("home"):
                home = Path(line.split("=", 1)[1].strip())
                for name in ("python.exe", "python3", "python"):
                    if (home / name).exists():
                        return str(home / name)
    except OSError:
        pass
    return sys.executable


def _inherited_python(python: str) -> str:
    """The interpreter a new --system-site-packages venv actually inherits.

    Creating a venv from inside another venv inherits the *base* install, not
    the parent venv. Probing the parent would promise the user that PySide6 is
    already here, and then hand them a venv that cannot see it.
    """
    script = ("import sys;"
              "print(sys.base_prefix if sys.base_prefix != sys.prefix else '')")
    try:
        out = subprocess.run([python, "-c", script], capture_output=True,
                             text=True, timeout=60, creationflags=_NO_WINDOW)
        base = out.stdout.strip()
    except Exception:
        return python
    if not base:
        return python                     # not a venv: it inherits itself
    for name in ("python.exe", "bin/python3", "bin/python"):
        candidate = Path(base) / name
        if candidate.exists():
            return str(candidate)
    return python


def _probe(python: str, modules: list[str]) -> dict[str, bool]:
    """Ask an interpreter which of these modules it can actually import."""
    if not modules:
        return {}
    script = (
        "import importlib.util, json, sys\n"
        "print(json.dumps({m: importlib.util.find_spec(m) is not None\n"
        "                  for m in sys.argv[1:]}))\n"
    )
    try:
        out = subprocess.run([python, "-c", script, *modules],
                             capture_output=True, text=True, timeout=90,
                             creationflags=_NO_WINDOW)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return {m: False for m in modules}


def _version_of(python: str) -> tuple[int, int]:
    try:
        out = subprocess.run(
            [python, "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"],
            capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
        major, minor = out.stdout.split()[:2]
        return int(major), int(minor)
    except Exception:
        return sys.version_info[:2]


class Plan:
    def __init__(self):
        self.run_with: str = sys.executable
        self.base: str = sys.executable
        self.create_venv = False
        self.install: list[Requirement] = []
        self.present: list[str] = []      # module names already on the machine
        self.ready = False


def survey() -> Plan:
    plan = Plan()
    modules = [r.module for r in REQUIREMENTS]

    venv = _venv_python()
    if venv is not None:
        found = _probe(str(venv), modules)
        if all(found.values()):
            plan.run_with = str(venv)
            plan.present = modules
            plan.ready = True
            return plan

    plan.base = _base_python()
    # What a new venv would inherit -- not necessarily what plan.base itself
    # can import, if plan.base is a venv.
    base_has = _probe(_inherited_python(plan.base), modules)

    if venv is None:
        if all(_probe(plan.base, modules).values()):
            # Everything is already here. Making a venv would only duplicate
            # a 300MB download for no benefit, so run against this Python.
            plan.run_with = plan.base
            plan.present = modules
            plan.ready = True
            return plan
        plan.create_venv = True
        plan.run_with = str(VENV_DIR / "Scripts" / "python.exe")
    else:
        plan.run_with = str(venv)
        # The venv inherits the base, so anything the base has counts as here.
        base_has = _probe(str(venv), modules)

    plan.present = [m for m, ok in base_has.items() if ok]
    plan.install = [r for r in REQUIREMENTS if not base_has.get(r.module)]
    return plan


# --------------------------------------------------------------------------
# install

def _log(message: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def install(plan: Plan, report) -> None:
    """Create the venv and pip-install the gaps. Raises on failure.

    `report(message, detail=False)` shows progress: the headline step when
    detail is false, a line of pip's own output when it is true.
    """
    lang = _language()

    if plan.create_venv:
        report(t("step_venv", lang))
        _run([plan.base, "-m", "venv", "--system-site-packages", str(VENV_DIR)],
             report)
        # Ask the venv itself what it can see rather than trusting the survey.
        # Whatever it inherited is genuinely here; whatever it did not, we
        # fetch -- and the manifest records it as downloaded, so uninstall
        # stays truthful either way.
        seen = _probe(plan.run_with, [r.module for r in REQUIREMENTS])
        plan.install = [r for r in REQUIREMENTS if not seen.get(r.module)]
        plan.present = [m for m, ok in seen.items() if ok]

    python = plan.run_with
    if not Path(python).exists():
        raise RuntimeError(f"missing interpreter: {python}")

    # A fresh venv can carry a pip too old for modern wheels.
    _run([python, "-m", "pip", "install", "--upgrade", "pip"], report,
         allow_failure=True)

    for requirement in plan.install:
        report(t("step_pip", lang, name=requirement.label(lang)))
        _run([python, "-m", "pip", "install", requirement.spec], report)

    # Confirm the app can actually start before claiming success. Every
    # requirement, not just the ones we installed: a package we expected to
    # inherit and did not is exactly as fatal as one that failed to download,
    # and it is the failure the user cannot diagnose.
    found = _probe(python, [r.module for r in REQUIREMENTS])
    broken = [m for m, ok in found.items() if not ok]
    if broken:
        raise RuntimeError(f"installed but not importable: {', '.join(broken)}")

    sys.path.insert(0, str(HERE))
    from app import manifest
    manifest.record_setup(
        python=python,
        venv_created=plan.create_venv,
        installed=[r.spec for r in plan.install],
        preexisting=plan.present,
    )


def _run(command: list[str], report, allow_failure: bool = False) -> None:
    _log("$ " + " ".join(command))
    process = subprocess.Popen(
        command, cwd=str(HERE), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", creationflags=_NO_WINDOW)
    tail: list[str] = []
    for line in process.stdout:
        line = line.rstrip()
        if not line:
            continue
        _log(line)
        tail.append(line)
        del tail[:-40]
        report(line, True)
    process.wait()
    if process.returncode and not allow_failure:
        raise RuntimeError("\n".join(tail[-6:]) or f"exit {process.returncode}")


def launch(python: str) -> None:
    """Start the app detached and let this process end."""
    windowless = Path(python).with_name(
        Path(python).name.replace("python.exe", "pythonw.exe"))
    if windowless.exists():
        python = str(windowless)
    subprocess.Popen([python, str(HERE / "run.py"), *sys.argv[1:]],
                     cwd=str(HERE), creationflags=_NO_WINDOW)


# --------------------------------------------------------------------------
# the window

def ask_and_install(plan: Plan) -> bool:
    """Show the plan, install if the user agrees. True if the app can start."""
    import tkinter as tk
    from tkinter import font as tkfont

    lang = _language()
    root = tk.Tk()
    root.title(t("title", lang))
    root.configure(bg="#FFFFFF")
    root.resizable(False, False)

    heading = tkfont.Font(family="Malgun Gothic", size=13, weight="bold")
    body = tkfont.Font(family="Malgun Gothic", size=9)
    small = tkfont.Font(family="Malgun Gothic", size=8)

    outcome = {"ok": False}
    frame = tk.Frame(root, bg="#FFFFFF", padx=26, pady=22)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="Engo", font=heading, bg="#FFFFFF", fg="#5B5BD6",
             anchor="w").pack(fill="x")
    tk.Label(frame, text=t("intro", lang), font=body, bg="#FFFFFF",
             fg="#3F3F46", anchor="w").pack(fill="x", pady=(2, 14))

    def section(title: str, items: list[str], colour: str) -> None:
        if not items:
            return
        tk.Label(frame, text=title, font=small, bg="#FFFFFF", fg=colour,
                 anchor="w").pack(fill="x", pady=(6, 2))
        for item in items:
            tk.Label(frame, text="   " + item, font=body, bg="#FFFFFF",
                     fg="#27272A", anchor="w").pack(fill="x")

    have = [f"· Python {sys.version_info[0]}.{sys.version_info[1]}"]
    have += [f"· {r.label(lang)}" for r in REQUIREMENTS
             if r.module in plan.present]
    need = [f"· {r.label(lang)}   ({r.mb} MB)" for r in plan.install]
    if plan.create_venv:
        need.append(f"· {t('venv', lang)}   (~5 MB)")

    section(t("have", lang), have, "#16A34A")
    section(t("need", lang), need, "#D97706")

    megabytes = sum(r.mb for r in plan.install) + (5 if plan.create_venv else 0)
    tk.Label(frame, text=t("total", lang, mb=megabytes), font=body,
             bg="#FFFFFF", fg="#27272A", anchor="w").pack(fill="x", pady=(12, 0))
    tk.Label(frame, text=t("where", lang, path=str(HERE)), font=small,
             bg="#FFFFFF", fg="#71717A", anchor="w", justify="left").pack(
        fill="x", pady=(8, 0))
    tk.Label(frame, text=t("note", lang), font=small, bg="#FFFFFF",
             fg="#71717A", anchor="w").pack(fill="x", pady=(2, 4))

    status = tk.Label(frame, text="", font=body, bg="#FFFFFF", fg="#5B5BD6",
                      anchor="w", wraplength=430, justify="left")
    detail = tk.Label(frame, text="", font=small, bg="#FFFFFF", fg="#A1A1AA",
                      anchor="w")

    buttons = tk.Frame(frame, bg="#FFFFFF")
    buttons.pack(fill="x", pady=(16, 0))

    def close() -> None:
        try:
            root.destroy()
        except Exception:
            pass

    cancel_btn = tk.Button(buttons, text=t("cancel", lang), font=body,
                           relief="flat", bg="#F4F4F5", fg="#3F3F46",
                           padx=18, pady=6, cursor="hand2", command=close)
    cancel_btn.pack(side="right")

    def start() -> None:
        go_btn.config(state="disabled", bg="#C7C7E8")
        cancel_btn.config(state="disabled")
        status.pack(fill="x", pady=(14, 0), before=buttons)
        detail.pack(fill="x", before=buttons)
        status.config(text=t("working", lang))

        # The window must not go away underneath the worker thread.
        root.protocol("WM_DELETE_WINDOW", lambda: None)

        def report(message: str, is_detail: bool = False) -> None:
            target = detail if is_detail else status
            text = message[:70] if is_detail else message
            try:
                root.after(0, lambda: target.config(text=text))
            except Exception:
                pass          # window already gone; the install still finishes

        def worker() -> None:
            try:
                install(plan, report)
            except Exception as exc:                       # noqa: BLE001
                _log(f"FAILED: {exc}")
                root.after(0, lambda: fail(str(exc)))
                return
            outcome["ok"] = True
            root.after(0, lambda: (status.config(text=t("done", lang)),
                                   detail.config(text=""),
                                   root.after(700, close)))

        threading.Thread(target=worker, daemon=True).start()

    def fail(message: str) -> None:
        status.config(text=t("failed", lang, err=message[:300],
                             log=str(LOG_PATH)), fg="#DC2626")
        detail.config(text="")
        cancel_btn.config(state="normal", text=t("close", lang))
        root.protocol("WM_DELETE_WINDOW", close)

    go_btn = tk.Button(buttons, text=t("go", lang), font=body, relief="flat",
                       bg="#5B5BD6", fg="#FFFFFF", padx=18, pady=6,
                       cursor="hand2", command=start,
                       activebackground="#4B4BC0", activeforeground="#FFFFFF")
    go_btn.pack(side="right", padx=(0, 8))

    root.update_idletasks()
    # Wide enough that the install path and the progress lines have room,
    # rather than letting tkinter shrink to the longest label.
    width = max(root.winfo_reqwidth(), 440)
    height = root.winfo_reqheight()
    root.geometry(f"{width}x{height}"
                  f"+{(root.winfo_screenwidth() - width) // 2}"
                  f"+{(root.winfo_screenheight() - height) // 3}")
    root.mainloop()
    return outcome["ok"]


def show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Engo", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


# --------------------------------------------------------------------------

def main() -> int:
    lang = _language()

    plan = survey()
    if plan.ready:
        launch(plan.run_with)
        return 0

    # Both checks come before the dialog: there is no point asking someone to
    # approve a 300MB download that cannot succeed.
    if path_too_deep():
        show_error(t("deep_path", lang, path=str(HERE)))
        return 1

    have = _version_of(plan.base)
    if have < MIN_PYTHON:
        show_error(t("old_python", lang,
                     have=".".join(map(str, have)),
                     need=".".join(map(str, MIN_PYTHON))))
        return 1

    if not ask_and_install(plan):
        return 1
    launch(plan.run_with)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:                              # noqa: BLE001
        import traceback
        _log(traceback.format_exc())
        show_error(f"{error}\n\n{LOG_PATH}")
        raise SystemExit(1)
