#!/usr/bin/env python3
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = (ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward").resolve()
SMOKE = (
    ROOT
    / "qc-workspace"
    / "SPY Plus 10 Walk-Forward - Defined Risk Option Smoke"
).resolve()
RELATIVE_PATHS = (
    Path("option_chain.py"),
    Path("option_risk.py"),
    Path("option_lifecycle.py"),
    Path("signals/__init__.py"),
    Path("signals/option_signal.py"),
)


def main() -> int:
    for relative in RELATIVE_PATHS:
        source = (PRIMARY / relative).resolve()
        source.relative_to(PRIMARY)
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = SMOKE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"option-smoke-sync:copied:{relative.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
