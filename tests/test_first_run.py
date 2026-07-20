"""The real first run: an empty folder, a bare Python, an actual download.

test_setup.py drives every branch with the interpreter probe stubbed out.
This one stubs nothing -- it builds a copy of the program in a temporary
folder, points bootstrap at a Python that has none of the dependencies, and
lets it download and install for real. That is the only way to catch the
failures a stub cannot have: a wheel that installs but will not import, a pip
that is too old, a venv that does not inherit what the survey promised.

It downloads roughly 325MB, so it is opt-in:

    .venv\\Scripts\\python.exe tests\\test_first_run.py --real

Without --real it prints what it would do and exits successfully.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def _bare_python() -> str | None:
    """A Python that is not this venv -- ideally the one that built it."""
    import sysconfig
    candidates = [Path(sysconfig.get_config_var("BINDIR") or "") / "python.exe",
                  Path(sys.base_prefix) / "python.exe",
                  Path(sys.base_prefix) / "bin" / "python3"]
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != Path(sys.executable).resolve():
            return str(candidate)
    return None


def main() -> int:
    if "--real" not in sys.argv:
        print("실제 내려받기 테스트입니다 (약 325MB).")
        print("실행하려면:  .venv\\Scripts\\python.exe tests\\test_first_run.py --real")
        return 0

    bare = _bare_python()
    if bare is None:
        print("  건너뜀: 의존성이 없는 Python 을 찾지 못했습니다")
        return 0

    # Windows caps paths at 260 characters and PySide6's tree is deep, so the
    # sandbox goes somewhere short rather than under %TEMP%.
    root = Path(tempfile.mkdtemp(prefix="engo_run_", dir="C:\\"
                                 if os.name == "nt" else None))
    try:
        for item in ("app", "bootstrap.py", "run.py", "requirements.txt"):
            source = ROOT / item
            target = root / item
            if source.is_dir():
                shutil.copytree(source, target,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, target)

        script = root / "_probe.py"
        script.write_text(
            "import json, sys\n"
            f"sys.path.insert(0, r'{root}')\n"
            "import bootstrap\n"
            "plan = bootstrap.survey()\n"
            "before = {'ready': plan.ready, 'venv': plan.create_venv,\n"
            "          'install': [r.spec for r in plan.install],\n"
            "          'present': list(plan.present)}\n"
            "bootstrap.install(plan, lambda *a, **k: None)\n"
            "found = bootstrap._probe(plan.run_with,\n"
            "                         [r.module for r in bootstrap.REQUIREMENTS])\n"
            "after = bootstrap.survey()\n"
            "from app import manifest\n"
            "print('@@' + json.dumps({'before': before, 'found': found,\n"
            "      'ready_now': after.ready, 'manifest': manifest.load(),\n"
            "      'python': plan.run_with}))\n",
            encoding="utf-8")

        print(f"[빈 폴더에서 실제 설치]  ({root})")
        print("  내려받는 중입니다. 몇 분 걸릴 수 있습니다…", flush=True)
        result = subprocess.run([bare, str(script)], capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=1800)
        line = next((l for l in result.stdout.splitlines()
                     if l.startswith("@@")), None)
        if line is None:
            check("설치가 끝났다", False,
                  (result.stdout + result.stderr)[-500:])
            return 1

        import json
        data = json.loads(line[2:])

        check("설치 전에는 준비가 안 됨", not data["before"]["ready"])
        check("가상환경을 만든다고 판단", data["before"]["venv"])
        check("받을 목록을 세웠다", bool(data["before"]["install"]),
              f"({data['before']['install']})")
        check("PySide6 를 import 할 수 있다", data["found"].get("PySide6"))
        check("piper 를 import 할 수 있다", data["found"].get("piper"))
        check("두 번째 실행은 바로 시작된다", data["ready_now"])
        check("받은 것이 기록되었다",
              bool(data["manifest"].get("packages_installed")),
              f"({data['manifest'].get('packages_installed')})")
        check("우리가 만든 가상환경으로 기록",
              data["manifest"].get("venv_created_by_setup") is True)
        check("가상환경 인터프리터를 쓴다", ".venv" in data["python"],
              data["python"])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("첫 실행 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
