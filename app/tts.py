"""Offline text-to-speech.

Uses Piper, a neural TTS that runs entirely on this machine -- no network, no
account, no per-request cost.

Two quality tiers ship for each gender. The `high` models are trained at
higher fidelity and are the default; the `medium` ones are kept because they
are a third of the size and synthesise three to four times faster, which
matters on a slow machine. Measured here:

    voice                 load     synth (5.5s of audio)   memory
    hfc_female (medium)   1.7s     0.30s                    85MB
    lessac     (high)     1.7s     0.99s                   127MB
    hfc_male   (medium)   1.4s     0.24s                    77MB
    ryan       (high)     1.0s     0.93s                   143MB

Memory is why this module is built the way it is: loading a voice costs more
than the rest of the program put together, so nothing is imported until the
first request, the model is released after two minutes of silence, and
synthesis happens on a worker thread so the first load never freezes the
window.
"""

from __future__ import annotations

import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from . import db

VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"


@dataclass(frozen=True)
class Voice:
    key: str
    gender: str          # "female" | "male"
    model: str           # piper voice name, e.g. "hfc_female"
    quality: str         # "high" | "medium"
    name_ko: str
    name_en: str
    default: bool = False    # downloaded on first run
    pitch_hz: int = 0        # measured median pitch of a statement

    @property
    def stem(self) -> str:
        """File stem, e.g. en_US-ryan-high (or en_GB-... for a UK voice)."""
        if self.model.startswith("en_GB-"):
            return f"en_GB-{self.model[len('en_GB-'):]}-{self.quality}"
        return f"en_US-{self.model}-{self.quality}"

    @property
    def filename(self) -> str:
        return f"{self.stem}.onnx"

    @property
    def path(self) -> Path:
        return VOICES_DIR / self.filename

    def exists(self) -> bool:
        return (self.path.exists()
                and (VOICES_DIR / f"{self.stem}.onnx.json").exists())

    def label(self, language: str) -> str:
        return self.name_en if language == "en" else self.name_ko

    def url(self, ext: str) -> str:
        return _slot_url(self.model, self.quality, ext)


# Four slots. Each one can be pointed at any Piper voice and given any name,
# so the shipped choice is a starting point rather than a fixed list.
SLOT_KEYS = ("slot1", "slot2", "slot3", "slot4")

# Pitch figures are measured, not guessed. The two "medium" voices are the
# defaults because they sit higher and lift more clearly at the end of a
# question; the "high" tier is a bigger model but speaks noticeably lower,
# which reads as flatter rather than better.
# All four are downloaded on first run so the shipped choice works out of the
# box; anything else from the catalogue is fetched only when a slot is pointed
# at it.
FACTORY_SLOTS: dict[str, Voice] = {
    v.key: v for v in (
        Voice("slot1", "female", "hfc_female", "medium",
              "여성 · 기본", "Female · default", default=True, pitch_hz=251),
        Voice("slot2", "male", "hfc_male", "medium",
              "남성 · 기본", "Male · default", default=True, pitch_hz=167),
        Voice("slot3", "female", "lessac", "high",
              "여성 · 낮은 톤 (Lessac)", "Female · lower (Lessac)",
              default=True, pitch_hz=187),
        Voice("slot4", "male", "ryan", "high",
              "남성 · 낮은 톤 (Ryan)", "Male · lower (Ryan)",
              default=True, pitch_hz=154),
    )
}
DEFAULT_VOICE = "slot1"

# Piper voices that can be picked for a slot, so the chooser needs no network.
# (name, quality, rough MB)
CATALOGUE = [
    ("hfc_female", "medium", 61), ("hfc_male", "medium", 61),
    ("amy", "medium", 61), ("kristin", "medium", 61),
    ("kathleen", "low", 21), ("ljspeech", "medium", 61),
    ("lessac", "medium", 61), ("lessac", "high", 109),
    ("ryan", "medium", 61), ("ryan", "high", 115),
    ("joe", "medium", 61), ("john", "medium", 61),
    ("bryce", "medium", 61), ("norman", "medium", 61),
    ("kusal", "medium", 61), ("sam", "medium", 61),
    ("libritts_r", "medium", 75), ("ljspeech", "high", 109),
    ("en_GB-alan", "medium", 61), ("en_GB-alba", "medium", 61),
    ("en_GB-jenny_dioco", "medium", 61), ("en_GB-cori", "high", 109),
]


def _slot_meta_key(slot: str) -> str:
    return f"tts_slot_{slot}"


def _load_slots() -> dict[str, Voice]:
    """Slot definitions, with any user edits applied over the factory ones."""
    import json
    slots: dict[str, Voice] = {}
    for key in SLOT_KEYS:
        base = FACTORY_SLOTS[key]
        raw = db.get_meta(_slot_meta_key(key), "")
        if not raw:
            slots[key] = base
            continue
        try:
            data = json.loads(raw)
            slots[key] = Voice(
                key=key,
                gender=data.get("gender", base.gender),
                model=data.get("model", base.model),
                quality=data.get("quality", base.quality),
                name_ko=data.get("name", base.name_ko),
                name_en=data.get("name", base.name_en),
                default=base.default,
                pitch_hz=base.pitch_hz if data.get("model") == base.model else 0,
            )
        except (ValueError, TypeError):
            slots[key] = base
    return slots


def save_slot(key: str, name: str, model: str, quality: str, gender: str) -> None:
    import json
    if key not in SLOT_KEYS:
        return
    db.set_meta(_slot_meta_key(key), json.dumps(
        {"name": name, "model": model, "quality": quality, "gender": gender},
        ensure_ascii=False))
    _refresh_voices()
    _engine.invalidate()


def reset_slot(key: str) -> None:
    db.set_meta(_slot_meta_key(key), "")
    _refresh_voices()
    _engine.invalidate()


VOICES: dict[str, Voice] = dict(FACTORY_SLOTS)


def _refresh_voices() -> None:
    """Re-read slot definitions from the database into VOICES.

    Update-then-prune rather than clear-then-update: the speech worker reads
    VOICES concurrently, and a clear() would open a window where a key it is
    about to look up does not exist.
    """
    fresh = _load_slots()
    VOICES.update(fresh)
    for stale in [k for k in VOICES if k not in fresh]:
        del VOICES[stale]


def reload_slots() -> None:
    _refresh_voices()

# Every earlier naming scheme, mapped onto the slot keys so an existing
# setting is carried forward instead of silently reset.
_LEGACY = {
    "female": "slot1", "male": "slot2",
    "female_medium": "slot1", "male_medium": "slot2",
    "female_high": "slot3", "male_high": "slot4",
}

# One-time correction: the high-pitched pair briefly shipped as the default,
# and anyone who never opened the menu is sitting on a choice they did not
# make. Move only those users, and only once.
_DEFAULT_FIX = "tts_default_v2"


def _apply_default_fix() -> None:
    if db.get_meta(_DEFAULT_FIX, ""):
        return
    db.set_meta(_DEFAULT_FIX, "1")
    if db.get_meta("tts_voice", "") in ("female_high", "male_high"):
        db.set_meta("tts_voice", DEFAULT_VOICE)


def _slot_url(model: str, quality: str, ext: str) -> str:
    """Catalogue entries may name a non-US locale as part of the model."""
    locale, name = ("en_US", model)
    if model.startswith("en_GB-"):
        locale, name = "en_GB", model[len("en_GB-"):]
    return (f"https://huggingface.co/rhasspy/piper-voices/resolve/main"
            f"/en/{locale}/{name}/{quality}/{locale}-{name}-{quality}{ext}")


def default_voices() -> list[Voice]:
    return [v for v in VOICES.values() if v.default]


def is_factory(key: str) -> bool:
    """True while a slot still points at the voice it shipped with.

    Compared on the model, not the name: renaming a slot does not stop it
    being one of the four voices the program comes with, and that is what the
    marker is telling the user.
    """
    factory = FACTORY_SLOTS.get(key)
    current = VOICES.get(key)
    if factory is None or current is None:
        return False
    return (current.model, current.quality) == (factory.model, factory.quality)


def missing_defaults() -> list[Voice]:
    """Default voices that still need downloading."""
    return [v for v in default_voices() if not v.exists()]


def download_bytes(voices) -> int:
    """Rough download size, for telling the user what they are agreeing to."""
    return sum(115_000_000 if v.quality == "high" else 61_000_000 for v in voices)

# Drop the loaded model after this long without a request.
IDLE_UNLOAD_SECONDS = 120

# Status callback, set by the UI. Called from the worker thread with one of
# "loading" / "speaking" / "idle" / "error" and the voice key.
_status_listener = None


def set_status_listener(callback) -> None:
    global _status_listener
    _status_listener = callback


def _status(state: str, voice_key: str = "") -> None:
    if _status_listener is None:
        return
    try:
        _status_listener(state, voice_key)
    except Exception:
        pass          # a broken listener must not silence the app


def available_voices() -> list[Voice]:
    return [v for v in VOICES.values() if v.exists()]


def installed() -> bool:
    """True when at least one voice is on disk (checked without importing piper)."""
    return any(v.exists() for v in VOICES.values())


def enabled() -> bool:
    return installed() and db.get_meta("tts_enabled", "1") == "1"


def set_enabled(on: bool) -> None:
    db.set_meta("tts_enabled", "1" if on else "0")


def voice_key() -> str:
    _apply_default_fix()
    stored = db.get_meta("tts_voice", DEFAULT_VOICE)
    stored = _LEGACY.get(stored, stored)
    if stored in VOICES and VOICES[stored].exists():
        return stored
    for fallback in (DEFAULT_VOICE, *VOICES):
        if VOICES[fallback].exists():
            return fallback
    return DEFAULT_VOICE


def voice() -> Voice:
    return VOICES[voice_key()]


def set_voice(key: str) -> None:
    if key in VOICES:
        db.set_meta("tts_voice", key)
        _engine.invalidate()


# Serialises downloads: the first-run dialog, the Data-tab button and the
# slot editor can all start one, and two writers on the same .part file would
# interleave into a corrupt model that passes the size check forever.
_download_lock = threading.Lock()


def download(voices, progress=None, should_stop=None) -> tuple[bool, str]:
    """Fetch voice models, reporting progress as (done_bytes, total_bytes, name).

    Each file lands on a .part first and is renamed once complete, so an
    interrupted download can never leave a truncated model that loads and then
    crashes. Serialised by a module lock (see above). Safe to call from a
    worker thread; never raises -- the outer except is what makes that
    promise true even for the rename and for a progress callback that blows
    up because its widget was destroyed.
    """
    import urllib.error
    import urllib.request

    voices = list(voices)
    total = download_bytes(voices)
    done = 0

    with _download_lock:
        try:
            VOICES_DIR.mkdir(parents=True, exist_ok=True)
            for voice in voices:
                # Config first: it is a few KB, so a wrong name or a dead
                # link fails in a moment instead of after 60MB.
                for ext in (".onnx.json", ".onnx"):
                    target = VOICES_DIR / f"{voice.stem}{ext}"
                    if target.exists() and target.stat().st_size > 1000:
                        continue
                    part = target.with_suffix(target.suffix + ".part")
                    cancelled = False
                    try:
                        request = urllib.request.Request(
                            voice.url(ext), headers={"User-Agent": "Engo"})
                        with urllib.request.urlopen(request, timeout=30) \
                                as response, open(part, "wb") as handle:
                            while True:
                                if should_stop is not None and should_stop():
                                    # Only flag it here. Windows refuses to
                                    # delete an open file, so cleanup must
                                    # wait until the handle is closed.
                                    cancelled = True
                                    break
                                chunk = response.read(1 << 16)
                                if not chunk:
                                    break
                                handle.write(chunk)
                                done += len(chunk)
                                if progress is not None:
                                    progress(done, total, voice.label("ko"))
                    except (urllib.error.URLError, TimeoutError, OSError) as exc:
                        part.unlink(missing_ok=True)
                        return False, str(exc)

                    if cancelled:
                        part.unlink(missing_ok=True)
                        return False, "cancelled"
                    part.replace(target)
            if progress is not None:
                progress(total, total, "")
            return True, ""
        except Exception as exc:            # noqa: BLE001 -- the no-raise contract
            return False, str(exc)


# Silence appended after every clip. Measured trailing silence straight out of
# the models: hfc_female 25ms, hfc_male 15ms, lessac 170ms -- and ryan 0ms, so
# its last consonant was being clipped off mid-sound and the playback stopped
# with an audible cut. Padding gives every voice room to finish.
TAIL_SILENCE_MS = 250


def _write_wav(voice, text: str, path) -> None:
    """Synthesise to a wav, keeping every chunk and padding the end.

    Uses the streaming API rather than synthesize_wav: measured on ryan-high,
    the one-shot call returned a shorter clip than concatenating the chunks
    itself produces.
    """
    chunks = list(voice.synthesize(text))
    if not chunks:
        return
    rate = chunks[0].sample_rate
    width = chunks[0].sample_width
    channels = chunks[0].sample_channels
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        for chunk in chunks:
            handle.writeframes(chunk.audio_int16_bytes)
        pad = int(rate * TAIL_SILENCE_MS / 1000) * width * channels
        handle.writeframes(b"\x00" * pad)


class _Engine:
    """Serialises synthesis on one worker thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._voice = None
        self._voice_key: str | None = None
        self._last_used = 0.0
        self._lock = threading.Lock()
        self._out_index = 0

    # -- public --------------------------------------------------------
    def say(self, text: str, key: str) -> None:
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
        self._queue.put((text[:600], key))

    def preload(self, key: str) -> None:
        """Warm a voice up so the first click is not the one that waits."""
        self._ensure_thread()
        self._queue.put((None, key))

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
            self._voice_key = None

    def shutdown(self) -> None:
        self.stop()
        if self._thread is not None:
            self._queue.put(None)

    @property
    def loaded_key(self) -> str | None:
        return self._voice_key

    # -- worker --------------------------------------------------------
    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="tts")
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
            text, key = item
            try:
                if text is None:
                    self._load(key)
                    _status("idle", key)
                else:
                    self._speak(text, key)
            except Exception:
                # A speech failure must never take the program down; the user
                # simply hears nothing.
                _status("error", key)

    def _maybe_unload(self) -> None:
        with self._lock:
            if (self._voice is not None
                    and time.monotonic() - self._last_used > IDLE_UNLOAD_SECONDS):
                self._voice = None
                self._voice_key = None

    def _load(self, key: str):
        with self._lock:
            if self._voice is not None and self._voice_key == key:
                return self._voice
        _status("loading", key)
        from piper import PiperVoice          # deferred: ~34MB of onnxruntime
        loaded = PiperVoice.load(str(VOICES[key].path))
        with self._lock:
            self._voice = loaded
            self._voice_key = key
        return loaded

    def _speak(self, text: str, key: str) -> None:
        loaded = self._load(key)
        self._last_used = time.monotonic()
        _status("speaking", key)

        # Alternate between two files so a still-playing clip is never the one
        # being overwritten.
        self._out_index ^= 1
        out = db.default_data_dir() / f"speech{self._out_index}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_wav(loaded, text, out)

        import winsound
        winsound.PlaySound(str(out), winsound.SND_FILENAME | winsound.SND_ASYNC)
        self._last_used = time.monotonic()
        _status("idle", key)


_engine = _Engine()


def speak(text: str) -> None:
    """Say `text` in the configured voice. Returns immediately."""
    if not enabled():
        return
    _engine.say(text, voice_key())


def preload() -> None:
    """Load the configured voice now, so the next click plays straight away."""
    if enabled():
        _engine.preload(voice_key())


def loaded_voice() -> str | None:
    return _engine.loaded_key


def stop() -> None:
    _engine.stop()


def shutdown() -> None:
    _engine.shutdown()
