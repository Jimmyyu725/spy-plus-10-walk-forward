#!/usr/bin/env python3
"""Copy the canonical v2 pure-Python modules into the cloud project."""

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "spy_plus_10" / "v2"
TARGET = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"
MODULES = ("evidence.py", "attribution.py")


def sync_modules() -> tuple[str, ...]:
    """Synchronize only from canonical source to the cloud project."""
    if not SOURCE.is_dir():
        raise RuntimeError(f"canonical v2 source is missing: {SOURCE}")
    if not TARGET.is_dir():
        raise RuntimeError(f"cloud v2 project is missing: {TARGET}")

    synced = []
    for name in MODULES:
        source = SOURCE / name
        if not source.is_file():
            raise RuntimeError(f"canonical v2 module is missing: {source}")
        shutil.copyfile(source, TARGET / name)
        synced.append(name)
    return tuple(synced)


if __name__ == "__main__":
    for module in sync_modules():
        print(f"SYNCED {module}")
