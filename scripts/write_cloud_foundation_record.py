#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spy_plus_10.foundation_record import render_foundation_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lean-version", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--result-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    text = render_foundation_record(
        lean_version=args.lean_version,
        git_commit=args.git_commit,
        organization_id=args.organization_id,
        result_url=args.result_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"foundation-record:wrote:{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
