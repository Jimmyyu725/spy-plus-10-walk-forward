#!/usr/bin/env python3
"""Copy the canonical v2 pure-Python modules into the cloud project."""

from pathlib import Path
import os
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "spy_plus_10" / "v2"
TARGET = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"
MODULES = ("evidence.py", "attribution.py")


def _stage_file(target: Path, name: str, content: bytes, mode: int) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target, prefix=f".{name}.", suffix=".sync.tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _restore_target(target: Path, name: str, original: tuple[bytes | None, int | None]) -> None:
    destination = target / name
    content, mode = original
    if content is None:
        destination.unlink(missing_ok=True)
        return
    temporary = _stage_file(target, name, content, mode)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def sync_modules(*, source: Path = SOURCE, target: Path = TARGET) -> tuple[str, ...]:
    """Synchronize only from canonical source to the cloud project."""
    source = Path(source)
    target = Path(target)
    if not source.is_dir():
        raise RuntimeError(f"canonical v2 source is missing: {source}")
    if not target.is_dir():
        raise RuntimeError(f"cloud v2 project is missing: {target}")

    source_paths = {name: source / name for name in MODULES}
    missing = [path for path in source_paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"canonical v2 module is missing: {missing[0]}")
    try:
        contents = {name: path.read_bytes() for name, path in source_paths.items()}
        source_modes = {name: path.stat().st_mode & 0o777 for name, path in source_paths.items()}
    except OSError as error:
        raise RuntimeError("cannot read canonical v2 module") from error

    originals = {}
    for name in MODULES:
        destination = target / name
        if destination.exists() and not destination.is_file():
            raise RuntimeError(f"cloud v2 target is not a file: {destination}")
        try:
            if destination.exists():
                originals[name] = (
                    destination.read_bytes(),
                    destination.stat().st_mode & 0o777,
                )
            else:
                originals[name] = (None, None)
        except OSError as error:
            raise RuntimeError(f"cannot read cloud v2 target: {destination}") from error

    staged = {}
    restore_required = []
    try:
        for name in MODULES:
            original_content, original_mode = originals[name]
            mode = original_mode if original_content is not None else source_modes[name]
            staged[name] = _stage_file(target, name, contents[name], mode)
        for name in MODULES:
            temporary = staged[name]
            restore_required.append(name)
            os.replace(temporary, target / name)
            staged.pop(name)
    except BaseException as error:
        restore_errors = []
        for name in reversed(restore_required):
            try:
                _restore_target(target, name, originals[name])
            except BaseException as restore_error:
                restore_errors.append(restore_error)
        if not isinstance(error, Exception):
            raise
        if restore_errors:
            raise RuntimeError("atomic sync failed and target restoration failed") from error
        raise RuntimeError("atomic sync failed") from error
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return MODULES


if __name__ == "__main__":
    for module in sync_modules():
        print(f"SYNCED {module}")
