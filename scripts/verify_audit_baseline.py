#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward"
sys.path.insert(0, str(PROJECT))

from baseline import load_baseline_contract


def main() -> int:
    required = (
        "audit.py",
        "baseline.py",
        "baseline-contract.json",
        "benchmark.py",
        "costs.py",
        "ledger.py",
        "metrics.py",
    )
    missing = [name for name in required if not (PROJECT / name).is_file()]
    if missing:
        print(f"audit-baseline:FAIL:missing={','.join(missing)}")
        return 1
    contract = load_baseline_contract(PROJECT / "baseline-contract.json")
    main_source = (PROJECT / "main.py").read_text(encoding="utf-8")
    if contract.formal_evaluation or contract.live_trading:
        print("audit-baseline:FAIL:unsafe-contract")
        return 1
    if "self.set_end_date(2015, 1, 9)" not in main_source:
        print("audit-baseline:FAIL:unbounded-smoke")
        return 1
    print("audit-baseline:PASS:formal_evaluation=false:live_trading=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
