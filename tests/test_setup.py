"""Setup and uninstall: what gets downloaded, and what gets deleted.

The two halves are the same question asked twice. Setup has to tell "already
on this computer" apart from "missing", because the user approves a download
size before it happens. Uninstall has to tell them apart again, because
deleting a library the user already had -- and that something else may depend
on -- is not ours to do.

No network here: the interpreter probe is replaced so every branch can be
driven. tests/test_first_run.py does the real download.

Run:  .venv\\Scripts\\python.exe tests\\test_setup.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = tempfile.mkdtemp(prefix="engo_setup_")
os.environ["ENGO_HOME"] = str(Path(_ROOT) / "data")

import bootstrap  # noqa: E402
from app import db, manifest, repo, uninstall  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def _fake_probe(available: set[str]):
    """Stand in for asking a real interpreter what it can import."""
    return lambda python, modules: {m: m in available for m in modules}


def test_survey() -> None:
    print("[설치 전 조사]")
    real_probe, real_venv = bootstrap._probe, bootstrap._venv_python
    bootstrap._venv_python = lambda windowless=False: None
    bootstrap._inherited_python = lambda python: python
    try:
        bootstrap._probe = _fake_probe({"PySide6", "piper"})
        plan = bootstrap.survey()
        check("다 있으면 바로 실행 준비", plan.ready)
        check("다 있으면 가상환경을 만들지 않는다", not plan.create_venv)
        check("다 있으면 받을 것이 없다", plan.install == [])

        bootstrap._probe = _fake_probe(set())
        plan = bootstrap.survey()
        check("하나도 없으면 준비 안 됨", not plan.ready)
        check("하나도 없으면 가상환경을 만든다", plan.create_venv)
        check("하나도 없으면 둘 다 받는다", len(plan.install) == 2,
              f"({[r.spec for r in plan.install]})")
        check("이미 있는 것으로 셈하지 않는다", plan.present == [],
              f"({plan.present})")

        bootstrap._probe = _fake_probe({"PySide6"})
        plan = bootstrap.survey()
        check("있는 것은 이미 있음으로 분류", plan.present == ["PySide6"],
              f"({plan.present})")
        check("없는 것만 받는다", [r.module for r in plan.install] == ["piper"],
              f"({[r.module for r in plan.install]})")
        megabytes = sum(r.mb for r in plan.install)
        check("보여줄 용량이 전체보다 작다",
              megabytes < sum(r.mb for r in bootstrap.REQUIREMENTS),
              f"({megabytes} MB < "
              f"{sum(r.mb for r in bootstrap.REQUIREMENTS)} MB)")
    finally:
        bootstrap._probe, bootstrap._venv_python = real_probe, real_venv


def test_long_path() -> None:
    print("\n[경로 길이]")
    real_here, real_long = bootstrap.HERE, bootstrap._long_paths_enabled
    try:
        bootstrap._long_paths_enabled = lambda: False
        bootstrap.HERE = Path("C:/Engo")
        check("짧은 경로는 통과", not bootstrap.path_too_deep())
        bootstrap.HERE = Path("C:/" + "a" * 200)
        check("긴 경로는 미리 걸러낸다", bootstrap.path_too_deep())
        bootstrap._long_paths_enabled = lambda: True
        check("긴 경로 지원이 켜져 있으면 통과", not bootstrap.path_too_deep())
    finally:
        bootstrap.HERE, bootstrap._long_paths_enabled = real_here, real_long


def test_manifest() -> None:
    print("\n[설치 기록]")
    real = manifest.MANIFEST_PATH
    manifest.MANIFEST_PATH = Path(_ROOT) / "install-manifest.json"
    try:
        manifest.record_setup(python="py", venv_created=True,
                              installed=["piper-tts>=1.5"],
                              preexisting=["PySide6"])
        check("받은 것을 기록한다",
              manifest.packages_installed() == ["piper-tts>=1.5"])
        check("원래 있던 것을 기록한다",
              manifest.packages_preexisting() == ["PySide6"])
        check("우리가 만든 가상환경임을 기록한다", manifest.venv_is_ours())

        # A second run must add to the record, never replace it.
        manifest.record_setup(python="py", venv_created=False,
                              installed=["extra"], preexisting=["PySide6"])
        check("다시 설치해도 이전 기록이 남는다",
              set(manifest.packages_installed())
              == {"piper-tts>=1.5", "extra"},
              f"({manifest.packages_installed()})")
        check("가상환경 표시가 지워지지 않는다", manifest.venv_is_ours())

        manifest.MANIFEST_PATH = Path(_ROOT) / "nope.json"
        check("기록이 없어도 터지지 않는다", manifest.load() == {})
    finally:
        manifest.MANIFEST_PATH = real


def test_uninstall_targets() -> None:
    print("\n[무엇을 지울지]")
    sandbox = Path(_ROOT) / "install"
    (sandbox / "voices").mkdir(parents=True)
    (sandbox / "voices" / "en_US-ryan-high.onnx").write_bytes(b"x" * 1000)
    (sandbox / "voices" / "en_US-ryan-high.onnx.json").write_bytes(b"{}")
    # a model the user copied in themselves -- not ours to delete
    (sandbox / "voices" / "my-paid-voice.onnx").write_bytes(b"x" * 500)
    (sandbox / ".venv" / "Scripts").mkdir(parents=True)
    (sandbox / ".venv" / "Scripts" / "python.exe").write_bytes(b"x" * 500)
    (sandbox / "mine.txt").write_text("a file the user put here")

    real = (uninstall.PROJECT_DIR, uninstall.VOICES_DIR, uninstall.VENV_DIR,
            manifest.MANIFEST_PATH)
    uninstall.PROJECT_DIR = sandbox
    uninstall.VOICES_DIR = sandbox / "voices"
    uninstall.VENV_DIR = sandbox / ".venv"
    manifest.MANIFEST_PATH = sandbox / "install-manifest.json"
    manifest.record_setup(python="py", venv_created=True,
                          installed=["piper-tts>=1.5"],
                          preexisting=["PySide6"])
    try:
        db.connect()
        repo.save_row("expressions", {"english": "a", "korean": "가",
                                      "tags": "", "studied_on": repo.today()})
        # the user keeps something of their own inside the data folder
        # (an ENGO_HOME pointed at a shared folder, say)
        data_dir = Path(_ROOT) / "data"
        (data_dir / "diary.txt").write_text("Engo가 만들지 않은 파일")
        targets = uninstall.data_targets()
        check("학습 데이터를 대상으로 잡는다", len(targets) == 1)
        check("폴더 전체가 아니라 아는 파일만 대상",
              targets[0].paths is not None
              and all("diary" not in p.name for p in targets[0].paths),
              f"({[p.name for p in (targets[0].paths or [])]})")

        keys = [x.key for x in uninstall.component_targets()]
        check("내려받은 음성이 대상", "voices" in keys, f"({keys})")
        check("내려받은 라이브러리가 대상", "venv" in keys, f"({keys})")
        check("원래 있던 것은 지우지 않는다고 알려준다",
              uninstall.kept_packages() == ["PySide6"])

        uninstall.close_everything()
        done, failed = uninstall.remove(targets)
        check("데이터베이스가 지워졌다", not (data_dir / "study.db").exists())
        check("실패 없음", not failed, f"({failed})")
        check("사용자 파일은 남고 그래서 폴더도 남는다",
              (data_dir / "diary.txt").exists())
        check("남긴 파일이 보고된다",
              any("diary" in p.name for x in done for p in x.leftovers),
              f"({[p.name for x in done for p in x.leftovers]})")

        # The point of sealing: shutting down must not rebuild what we erased.
        db.set_meta("device_name", "유령")
        check("지운 뒤 데이터베이스가 되살아나지 않는다",
              not (data_dir / "study.db").exists())
        check("그래도 쓰기가 예외를 내지 않는다 (종료 경로 보호)",
              db.get_meta("device_name") == "유령")

        # ...and if deletion had failed, unseal() goes back to the real file.
        db.unseal()
        check("삭제 실패 시 봉인을 풀 수 있다", not db._sealed)
        db.seal()

        parts = uninstall.component_targets()
        uninstall.remove(parts)
        check("내려받은 음성이 지워졌다",
              not (sandbox / "voices" / "en_US-ryan-high.onnx").exists())
        check("직접 넣은 음성 파일은 남는다",
              (sandbox / "voices" / "my-paid-voice.onnx").exists())
        check("라이브러리가 지워졌다", not (sandbox / ".venv").exists())
        check("우리가 안 만든 파일은 그대로", (sandbox / "mine.txt").exists())
        check("프로그램 폴더 자체는 남는다 (사용자가 직접 삭제)", sandbox.exists())
    finally:
        (uninstall.PROJECT_DIR, uninstall.VOICES_DIR, uninstall.VENV_DIR,
         manifest.MANIFEST_PATH) = real
        db._sealed = False


def test_ownership() -> None:
    print("\n[직접 만든 .venv 는 지우지 않는다]")
    sandbox = Path(_ROOT) / "own"
    (sandbox / ".venv").mkdir(parents=True)
    real = (uninstall.VENV_DIR, uninstall.VOICES_DIR, manifest.MANIFEST_PATH)
    uninstall.VENV_DIR = sandbox / ".venv"
    uninstall.VOICES_DIR = sandbox / "voices"          # does not exist
    manifest.MANIFEST_PATH = sandbox / "install-manifest.json"
    try:
        # No manifest at all -- the record was lost. Err toward keeping.
        keys = [x.key for x in uninstall.component_targets()]
        check("기록이 없으면 venv 를 지우지 않는다", "venv" not in keys,
              f"({keys})")
        check("남겨 둔다고 알 수 있다", uninstall.venv_kept())

        # A manifest that says setup did NOT create it: same answer.
        manifest.record_setup(python="py", venv_created=False,
                              installed=["piper-tts>=1.5"], preexisting=[])
        keys = [x.key for x in uninstall.component_targets()]
        check("직접 만든 venv 는 대상이 아니다", "venv" not in keys, f"({keys})")

        # Only a venv the setup step itself created is fair game.
        manifest.record_setup(python="py", venv_created=True,
                              installed=[], preexisting=[])
        keys = [x.key for x in uninstall.component_targets()]
        check("설치가 만든 venv 만 대상이 된다", "venv" in keys, f"({keys})")
    finally:
        uninstall.VENV_DIR, uninstall.VOICES_DIR, manifest.MANIFEST_PATH = real


def test_deferred() -> None:
    print("\n[실행 중인 가상환경]")
    sandbox = Path(_ROOT) / "running"
    (sandbox / ".venv").mkdir(parents=True)
    real_venv, real_running = uninstall.VENV_DIR, uninstall._running_from_venv
    real_manifest = manifest.MANIFEST_PATH
    uninstall.VENV_DIR = sandbox / ".venv"
    uninstall._running_from_venv = lambda: True
    manifest.MANIFEST_PATH = sandbox / "install-manifest.json"
    manifest.record_setup(python="py", venv_created=True,
                          installed=[], preexisting=[])
    try:
        target = [x for x in uninstall.component_targets() if x.key == "venv"][0]
        check("지금은 못 지운다고 표시된다", target.deferred)
        uninstall.remove([target])
        check("실제로 지우지 않는다", (sandbox / ".venv").exists())
    finally:
        uninstall.VENV_DIR = real_venv
        uninstall._running_from_venv = real_running
        manifest.MANIFEST_PATH = real_manifest


def main() -> int:
    test_survey()
    test_long_path()
    test_manifest()
    test_uninstall_targets()
    test_ownership()
    test_deferred()

    db.close()
    shutil.rmtree(_ROOT, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 설치·삭제 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
