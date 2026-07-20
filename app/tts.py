"""Offline text-to-speech.

Uses Piper, a neural TTS that runs entirely on this machine -- no network, no
account, no per-request cost. Two voices ship with the app, one male and one
female; which one is used is a setting.

Memory is the reason this module is built the way it is. Measured on this
machine, importing onnxruntime costs ~34MB and loading a voice another ~85MB,
which is more than the rest of the program put together. So:

  * nothing is imported until the first time the user asks to hear something
  * the voice is released after a couple of minutes of silence
  * synthesis happens on a worker thread, so the 1.4s first load never freezes
    the window

That keeps a tray-resident app back at its normal footprint between uses.
"""

from __future__ import annotations

import queue
import threading
import time
import wave
from pathlib import Path

from . import db

VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"
VOICE_FILES = {
    "female": "en_US-hfc_female-medium.onnx",
    "male": "en_US-hfc_male-medium.onnx",
}
DEFAULT_VOICE = "female"

# Drop the loaded model after this long without a request.
IDLE_UNLOAD_SECONDS = 120


def voice_path(gender: str) -> Path:
    return VOICES_DIR / VOICE_FILES.get(gender, VOICE_FILES[DEFAULT_VOICE])


def installed() -> bool:
    """True when both voices are on disk. Checked without importing piper."""
    return all(voice_path(g).exists() for g in VOICE_FILES)


def enabled() -> bool:
    return installed() and db.get_meta("tts_enabled", "1") == "1"


def set_enabled(on: bool) -> None:
    db.set_meta("tts_enabled", "1" if on else "0")


def gender() -> str:
    value = db.get_meta("tts_voice", DEFAULT_VOICE)
    return value if value in VOICE_FILES else DEFAULT_VOICE


def set_gender(value: str) -> None:
    if value in VOICE_FILES:
        db.set_meta("tts_voice", value)
        _engine.invalidate()


class _Engine:
    """Serialises synthesis on one worker thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._voice = None
        self._voice_gender: str | None = None
        self._last_used = 0.0
        self._lock = threading.Lock()
        self._out_index = 0

    # -- public --------------------------------------------------------
    def say(self, text: str, gender_: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._ensure_thread()
        # Only the newest request matters; drop anything still waiting so a
        # burst of clicks does not queue up a minute of speech.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put((text[:600], gender_))

    def stop(self) -> None:
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def invalidate(self) -> None:
        """Forget the loaded model -- called when the voice setting changes."""
        with self._lock:
            self._voice = None
            self._voice_gender = None

    def shutdown(self) -> None:
        self.stop()
        if self._thread is not None:
            self._queue.put(None)

    # -- worker --------------------------------------------------------
    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="tts")
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=5.0)
            except queue.Empty:
                self._maybe_unload()
                continue
            if item is None:
                return
            text, gender_ = item
            try:
                self._speak(text, gender_)
            except Exception:
                # A speech failure must never take the program down; the user
                # simply hears nothing.
                pass

    def _maybe_unload(self) -> None:
        with self._lock:
            if (self._voice is not None
                    and time.monotonic() - self._last_used > IDLE_UNLOAD_SECONDS):
                self._voice = None
                self._voice_gender = None

    def _load(self, gender_: str):
        with self._lock:
            if self._voice is not None and self._voice_gender == gender_:
                return self._voice
        from piper import PiperVoice          # deferred: ~34MB of onnxruntime
        voice = PiperVoice.load(str(voice_path(gender_)))
        with self._lock:
            self._voice = voice
            self._voice_gender = gender_
        return voice

    def _speak(self, text: str, gender_: str) -> None:
        voice = self._load(gender_)
        self._last_used = time.monotonic()

        # Alternate between two files so a still-playing clip is never the one
        # being overwritten.
        self._out_index ^= 1
        out = db.default_data_dir() / f"speech{self._out_index}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as handle:
            voice.synthesize_wav(text, handle)

        import winsound
        winsound.PlaySound(str(out), winsound.SND_FILENAME | winsound.SND_ASYNC)
        self._last_used = time.monotonic()


_engine = _Engine()


def speak(text: str) -> None:
    """Say `text` in the configured voice. Returns immediately."""
    if not enabled():
        return
    _engine.say(text, gender())


def stop() -> None:
    _engine.stop()


def shutdown() -> None:
    _engine.shutdown()
