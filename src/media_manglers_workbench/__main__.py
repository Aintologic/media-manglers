"""Command entry point for the source-run workbench."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from .app import main as app_main
    except ImportError as exc:
        print(
            "Video Mangler Workbench needs PySide6. Install the GUI extra with "
            "py -m pip install -e .[gui] from the repo root.",
            file=sys.stderr,
        )
        print(f"Import error: {exc}", file=sys.stderr)
        return 2
    return app_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
