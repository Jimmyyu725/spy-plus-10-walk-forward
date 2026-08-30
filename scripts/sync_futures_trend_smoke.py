#!/usr/bin/env python3
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = (ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward").resolve()
SMOKE = (
    ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward - Futures Trend Smoke"
).resolve()
RELATIVE_PATHS = (
    Path("futures_allocation.py"),
    Path("futures_roll.py"),
    Path("signals/__init__.py"),
    Path("signals/futures_trend.py"),
)


def main() -> int:
    for relative in RELATIVE_PATHS:
        source = (PRIMARY / relative).resolve()
        try:
            source.relative_to(PRIMARY)
        except ValueError as exc:
            raise RuntimeError(f"source escaped primary project: {source}") from exc
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = SMOKE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"futures-smoke-sync:copied:{relative.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
