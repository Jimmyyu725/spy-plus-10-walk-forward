"""Verify that the v2 project remains evidence-only."""

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
from spy_plus_10.v2_foundation import validate_v2_foundation


def main() -> None:
    status = validate_v2_foundation(REPOSITORY_ROOT)
    print(f"V2_FOUNDATION_OK project={status.project_name} mode={status.mode}")


if __name__ == "__main__":
    main()
