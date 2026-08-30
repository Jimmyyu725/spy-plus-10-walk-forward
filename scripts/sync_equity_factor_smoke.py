#!/usr/bin/env python3
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = (ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward").resolve()
SMOKE = (
    ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Equity Factor Smoke"
).resolve()
RELATIVE_PATHS = (
    Path("universe.py"),
    Path("equity_allocation.py"),
    Path("signals/__init__.py"),
    Path("signals/equity_factor.py"),
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
        print(f"equity-smoke-sync:copied:{relative.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
