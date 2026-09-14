"""Package entry point so ``python -m src.cli`` dispatches the Typer app."""

from __future__ import annotations

from src.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
