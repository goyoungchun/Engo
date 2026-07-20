"""Launcher. `pythonw run.py` starts the app; `--tray` starts it minimised."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
