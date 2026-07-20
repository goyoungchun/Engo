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
    available = tts.available_voices()
    check("음성이 하나 이상 설치됨", tts.installed(), f"({tts.VOICES_DIR})")
    if not tts.installed():
        print("\n음성 모델이 없어 나머지 검사를 건너뜁니다.")
        return 1
    print(f"  사용 가능: {', '.join(v.key for v in available)}")
    check("기본값은 켜짐", tts.enabled())
    check("기본 목소리는 1번 칸", tts.voice_key() == "slot1", f"({tts.voice_key()})")
    check("칸이 4개", len(tts.SLOT_KEYS) == 4)
    check("남녀 각각 최소 하나씩 있음",
          {v.gender for v in available} == {"female", "male"})

    print("\n[음정: 기본 음성이 더 높게 말한다]")
    # Measured, not assumed -- the "high" tier is a bigger model but speaks
    # lower, which is why it is not the default.
    for gender in ("female", "male"):
        higher = next(v for v in tts.VOICES.values()
                      if v.gender == gender and v.quality == "medium")
        lower = next(v for v in tts.VOICES.values()
                     if v.gender == gender and v.quality == "high")
        check(f"{gender}: 기본({higher.pitch_hz}Hz)이 "
              f"낮은 톤({lower.pitch_hz}Hz)보다 높다",
              higher.pitch_hz > lower.pitch_hz)
    check("네 칸 모두 첫 실행에 받는다",
          len(tts.default_voices()) == 4, f"({len(tts.default_voices())}개)")

    print("\n[옛 설정값 이전]")
    for old, expected in (("female", "slot1"), ("male", "slot2"),
                          ("female_medium", "slot1"), ("male_high", "slot4")):
        db.set_meta("tts_voice", old)
        check(f"'{old}' → {expected}", tts.voice_key() == expected,
              tts.voice_key())
    db.set_meta("tts_voice", "nonsense")
    check("알 수 없는 값이면 기본값으로", tts.voice_key() in tts.VOICES,
          tts.voice_key())

    print("\n[칸을 직접 설정하기]")
    original = tts.VOICES["slot3"]
    tts.save_slot("slot3", "내 목소리", "amy", "medium", "female")
    check("이름이 바뀐다", tts.VOICES["slot3"].label("ko") == "내 목소리",
          tts.VOICES["slot3"].label("ko"))
    check("모델이 바뀐다", tts.VOICES["slot3"].model == "amy",
          tts.VOICES["slot3"].model)
    check("파일 이름도 따라 바뀐다",
          tts.VOICES["slot3"].stem == "en_US-amy-medium",
          tts.VOICES["slot3"].stem)
    check("아직 안 받았으므로 목록에 없다",
          "slot3" not in {v.key for v in tts.available_voices()})

    tts.save_slot("slot3", "영국 남성", "en_GB-alan", "medium", "male")
    check("영국 음성도 경로가 맞는다",
          tts.VOICES["slot3"].stem == "en_GB-alan-medium",
          tts.VOICES["slot3"].stem)
    check("내려받기 주소에 en_GB가 들어간다",
          "/en_GB/" in tts.VOICES["slot3"].url(".onnx"),
          tts.VOICES["slot3"].url(".onnx"))

    tts.reset_slot("slot3")
    check("기본값으로 되돌린다", tts.VOICES["slot3"].model == original.model,
          tts.VOICES["slot3"].model)
    check("되돌리면 다시 쓸 수 있다", tts.VOICES["slot3"].exists())

    print("\n[상태 알림]")
    seen: list[tuple[str, str]] = []
    tts.set_status_listener(lambda state, key: seen.append((state, key)))

    print("\n[각 음성이 실제 소리를 만드는지]")
    baseline = rss_mb()
    produced = {}
    for voice in [v.key for v in available]:
        tts.set_voice(voice)
        check(f"{voice} 설정이 저장됨", tts.voice_key() == voice)

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

    distinct = {bytes(v) for v in produced.values()}
    check("각 음성이 서로 다른 소리를 냄", len(distinct) == len(produced),
          f"({len(distinct)}/{len(produced)} 서로 다름)")

    loaded = rss_mb()
    print(f"\n  모델 로드 후 메모리 {loaded:.0f} MB (기준 {baseline:.0f} MB)")

    # Snapshot now: the truncation checks below load models directly, which
    # appends more status events and would hide what speaking actually did.
    speak_states = [state for state, _ in seen]
    speak_keys = [key for _, key in seen]

    print("\n[끝까지 읽는지 — 잘림 검사]")
    # ryan-high leaves no trailing silence of its own, so its final consonant
    # was being clipped and playback stopped mid-sound. Every clip must end
    # quietly, or the user hears it cut off.
    import numpy as np
    for voice in available:
        engine_voice = tts._engine._load(voice.key)
        for label, text in (("짧은 문장", "Break the ice."),
                            ("물음표", "Are you coming with us?"),
                            ("긴 문장", "Remote work was once a perk. Today it "
                                      "is a baseline expectation for many "
                                      "knowledge workers.")):
            path = Path(_ROOT) / f"cut_{voice.key}.wav"
            tts._write_wav(engine_voice, text, path)
            with wave.open(str(path)) as handle:
                rate, frames = handle.getframerate(), handle.getnframes()
                raw = handle.readframes(frames)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            tail = samples[-int(rate * 0.05):]
            rms = float(np.sqrt((tail ** 2).mean()))
            check(f"{voice.key} / {label}: 소리 중간에 끊기지 않음", rms < 0.01,
                  f"(끝 50ms 세기 {rms:.4f})")

    print("\n[상태 알림 내용]")
    check("음성 불러오는 중 알림이 왔음", "loading" in speak_states,
          str(set(speak_states)))
    check("읽는 중 알림이 왔음", "speaking" in speak_states)
    check("읽기가 끝나면 idle 로 돌아감",
          speak_states and speak_states[-1] == "idle",
          speak_states[-1] if speak_states else "(없음)")
    check("알림에 어떤 음성인지 담겨 있음",
          all(key in tts.VOICES for key in speak_keys if key))
    tts.set_status_listener(None)

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
