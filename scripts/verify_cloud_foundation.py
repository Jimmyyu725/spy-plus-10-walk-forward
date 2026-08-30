#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spy_plus_10.foundation import FoundationValidationError, validate_foundation


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        status = validate_foundation(root)
    except FoundationValidationError as exc:
        print(f"foundation:FAIL:{exc}")
        return 1
    print(
        "foundation:PASS:"
        f"project={status.project_name}:mode={status.mode}:"
        f"formal_evaluation={str(status.formal_evaluation).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
