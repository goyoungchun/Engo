"""First-run voice download.

The download really runs -- against a real HuggingFace URL -- because the
parts that break are the ones a stub cannot exercise: a wrong URL, a partial
file left behind by an interruption, or a model that downloads but does not
load. To keep it quick only the small companion .json is fetched in full; the
big .onnx is checked for reachability and then cancelled.

Run:  .venv\\Scripts\\python.exe tests\\test_voice_download.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = tempfile.mkdtemp(prefix="engo_dl_")
os.environ["ENGO_HOME"] = _ROOT

from app import db, tts  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def main() -> int:
    db.connect()
    real_dir = tts.VOICES_DIR
    sandbox = Path(_ROOT) / "voices"
    tts.VOICES_DIR = sandbox          # never touch the real models

    try:
        print("[빈 상태에서의 판정]")
        check("설치된 음성이 없다고 본다", not tts.installed())
        check("기본 음성 2개가 빠졌다고 본다", len(tts.missing_defaults()) == 2,
              f"({len(tts.missing_defaults())}개)")
        size = tts.download_bytes(tts.missing_defaults()) / 1024 / 1024
        check("받아야 할 크기를 알려준다", 100 < size < 200, f"({size:.0f} MB)")

        print("\n[실제 내려받기]")
        voice = tts.VOICES["female_medium"]
        seen: list[tuple[int, int]] = []

        # Fetch only the small .json in full: cancel as soon as the big model
        # starts, which also exercises the cancel path.
        started_big = {"yes": False}

        def should_stop():
            if (sandbox / f"en_US-{voice.model}-{voice.quality}.onnx.part").exists():
                started_big["yes"] = True
                return True
            return False

        ok, message = tts.download(
            [voice], progress=lambda d, t_, n: seen.append((d, t_)),
            should_stop=should_stop)
        check("큰 모델을 만나 취소되었다", not ok and message == "cancelled",
              f"(ok={ok}, {message})")
        check("진행률 보고가 왔다", bool(seen), f"({len(seen)}회)")

        json_file = sandbox / f"en_US-{voice.model}-{voice.quality}.onnx.json"
        check("설정 파일은 완전히 받아졌다",
              json_file.exists() and json_file.stat().st_size > 1000,
              f"({json_file.stat().st_size if json_file.exists() else 0} bytes)")
        leftovers = list(sandbox.glob("*.part"))
        check("취소된 파일 조각이 남지 않았다", not leftovers,
              f"({[p.name for p in leftovers]})")
        check("반쪽짜리 모델을 '설치됨'으로 세지 않는다", not voice.exists())

        print("\n[이미 받은 파일은 다시 받지 않는다]")
        before = json_file.stat().st_mtime_ns
        tts.download([voice], should_stop=lambda: True)
        check("기존 파일을 건드리지 않는다",
              json_file.stat().st_mtime_ns == before)

        print("\n[잘못된 주소]")
        broken = tts.Voice("broken", "female", "nope_does_not_exist", "medium",
                           "x", "x")
        ok, message = tts.download([broken])
        check("실패를 예외 없이 알려준다", not ok and bool(message), message[:60])
        check("실패해도 조각을 남기지 않는다", not list(sandbox.glob("*.part")))

    finally:
        tts.VOICES_DIR = real_dir

    print("\n[진짜 폴더는 그대로]")
    check("실제 음성 폴더를 건드리지 않았다", tts.installed(), str(real_dir))

    db.close()
    shutil.rmtree(_ROOT, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 음성 내려받기 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
