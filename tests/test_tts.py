"""Text-to-speech tests. Needs the voice models in voices/.

Verifies the two things that can silently go wrong: that a voice actually
produces audio (rather than a zero-length file), and that the model is
released when idle -- an always-loaded voice would add ~85MB to a program
that spends most of its life in the tray.

Run:  .venv\\Scripts\\python.exe tests\\test_tts.py
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import time
import wave
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = tempfile.mkdtemp(prefix="studyenglish_tts_")
os.environ["STUDYENGLISH_HOME"] = _ROOT

from app import db, tts  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_mb() -> float:
    fn = ctypes.windll.kernel32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    handle = ctypes.windll.kernel32.GetCurrentProcess
    handle.restype = wintypes.HANDLE
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    fn(handle(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1024 / 1024


def wait_for_audio(path: Path, timeout: float = 40.0) -> bool:
    """Speech runs on a worker thread, so poll for the file it writes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 1000:
            time.sleep(0.3)          # let the write finish
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    print(f"임시 데이터 위치: {_ROOT}")
    db.connect()

    print("\n[설치 상태]")
    check("두 음성 파일이 모두 있음", tts.installed(),
          f"({tts.VOICES_DIR})")
    if not tts.installed():
        print("\n음성 모델이 없어 나머지 검사를 건너뜁니다.")
        return 1
    check("기본값은 켜짐", tts.enabled())
    check("기본 목소리는 여성", tts.gender() == "female", f"({tts.gender()})")

    print("\n[남/여 목소리가 실제 소리를 만드는지]")
    baseline = rss_mb()
    produced = {}
    for voice in ("female", "male"):
        tts.set_gender(voice)
        check(f"{voice} 설정이 저장됨", tts.gender() == voice)

        for old in Path(_ROOT).glob("speech*.wav"):
            old.unlink(missing_ok=True)
        tts.speak("Break the ice means to make people feel more comfortable.")

        found = None
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and found is None:
            for candidate in Path(_ROOT).glob("speech*.wav"):
                if candidate.stat().st_size > 1000:
                    found = candidate
                    break
            time.sleep(0.2)
        ok = found is not None and wait_for_audio(found)
        check(f"{voice}: 음성 파일이 만들어짐", ok)
        if not ok:
            continue

        with wave.open(str(found)) as handle:
            frames, rate = handle.getnframes(), handle.getframerate()
            data = handle.readframes(frames)
        seconds = frames / rate
        check(f"{voice}: 길이가 그럴듯함", 1.0 < seconds < 20.0, f"({seconds:.1f}초)")
        check(f"{voice}: 무음이 아님", max(data[:2000], default=0) > 0)
        produced[voice] = bytes(data)

    if len(produced) == 2:
        check("남/여 음성이 서로 다름", produced["female"] != produced["male"])

    loaded = rss_mb()
    print(f"\n  모델 로드 후 메모리 {loaded:.0f} MB (기준 {baseline:.0f} MB)")

    print("\n[유휴 시 모델 해제]")
    check("지금은 모델이 올라와 있음", tts._engine._voice is not None)
    # Rather than waiting two real minutes, move the clock back.
    tts._engine._last_used = time.monotonic() - (tts.IDLE_UNLOAD_SECONDS + 5)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and tts._engine._voice is not None:
        time.sleep(0.5)
    check("유휴 상태가 되면 모델이 해제됨", tts._engine._voice is None)

    print("\n[끄기]")
    tts.set_enabled(False)
    for old in Path(_ROOT).glob("speech*.wav"):
        old.unlink(missing_ok=True)
    tts.speak("This must not be spoken.")
    time.sleep(2.0)
    check("꺼져 있으면 아무것도 만들지 않음",
          not any(Path(_ROOT).glob("speech*.wav")))
    tts.set_enabled(True)

    tts.shutdown()
    db.close()
    shutil.rmtree(_ROOT, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 TTS 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
