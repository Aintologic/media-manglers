"""Deployment entry point used by the standalone Windows build."""

from __future__ import annotations

from pathlib import Path
import sys


if not getattr(sys, "frozen", False):
    SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))

from media_manglers_workbench.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
