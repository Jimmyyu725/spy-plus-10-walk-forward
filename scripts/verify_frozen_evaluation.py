#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spy_plus_10.frozen_evaluation import (
    extract_cloud_statistics,
    verify_frozen_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify frozen evidence")
    parser.add_argument("evidence_dir", type=Path)
    arguments = parser.parse_args()
    evidence_dir = arguments.evidence_dir
    payload = json.loads(
        (evidence_dir / "daily-evidence.json").read_text(encoding="utf-8")
    )
    backtest = json.loads(
        (evidence_dir / "backtest.json").read_text(encoding="utf-8")
    )
    result = verify_frozen_evidence(payload, extract_cloud_statistics(backtest))
    (evidence_dir / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(result["status"])
    return 0 if result["status"] in {"PASS", "FAIL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
