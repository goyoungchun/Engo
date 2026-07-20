"""Download the two Piper voices Engo speaks with.

They are ~60MB each, so they are not kept in the repository. Run this once
after cloning:

    python tools/get_voices.py

Without them the program still works -- the 🔊 buttons simply stay hidden.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main"
        "/en/en_US/{name}/medium/en_US-{name}-medium{ext}")
VOICES = ("hfc_female", "hfc_male")
TARGET = Path(__file__).resolve().parent.parent / "voices"


def download(url: str, path: Path) -> None:
    print(f"  {path.name} … ", end="", flush=True)
    if path.exists() and path.stat().st_size > 1000:
        print("already there")
        return
    with urllib.request.urlopen(url) as response, open(path, "wb") as handle:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while chunk := response.read(1 << 16):
            handle.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {path.name} … {done * 100 // total}%",
                      end="", flush=True)
    print(f"\r  {path.name} … {path.stat().st_size / 1024 / 1024:.0f} MB")


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Piper voices into {TARGET}")
    for name in VOICES:
        for ext in (".onnx", ".onnx.json"):
            url = BASE.format(name=name, ext=ext)
            try:
                download(url, TARGET / f"en_US-{name}-medium{ext}")
            except Exception as exc:
                print(f"\n  failed: {exc}")
                return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
