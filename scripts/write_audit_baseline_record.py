#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spy_plus_10.audit_baseline_record import render_audit_baseline_record
from spy_plus_10.foundation_record import parse_result_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lean-version", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--result-url", required=True)
    parser.add_argument("--test-count", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    project_id, backtest_id = parse_result_url(args.result_url)
    text = render_audit_baseline_record(
        lean_version=args.lean_version,
        git_commit=args.git_commit,
        project_id=project_id,
        backtest_id=backtest_id,
        result_url=args.result_url,
        test_count=args.test_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"audit-baseline-record:wrote:{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
