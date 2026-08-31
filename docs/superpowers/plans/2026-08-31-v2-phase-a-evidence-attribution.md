# V2 Phase A Evidence and Attribution Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不实现任何经济策略、参数优化或交易逻辑的前提下，建立独立 v2 QuantConnect 项目，实测 Object Store 字符串与 bytes 通道，并完成分年证据、manifest、下载、独立验证、日度 sleeve 归因和 ablation 数据接口。

**Architecture:** `spy_plus_10/v2/` 是纯 Python 证据、归因与验证逻辑的唯一源码；同步脚本把云端可用模块逐字复制到独立项目 `qc-workspace/SPY Plus 10 Walk-Forward v2/`，同步测试防止双份代码漂移。云端 capability backtest 只写入确定性的 1 KB probes、两日合成证据块和 manifest，不订阅证券、不发订单；Atlas 通过 QuantConnect 分页 API 列出并下载对象，再由不导入云端算法评价实现的本地验证器复算长度、SHA-256、日期、账本和归因守恒。

**Tech Stack:** Python 3.12、QuantConnect LEAN Python API、LEAN CLI、QuantConnect REST API、gzip、base64、JSON、`decimal.Decimal`、`unittest`、Git/GitHub private repository。

---

## 固定边界与完成定义

- 本计划只交付批准规范的 Phase A，不实现动态 SPY、股票 Alpha、期货 Alpha、期权保护、27 组参数搜索或经济回测。
- 新云端项目名称必须精确为 `SPY Plus 10 Walk-Forward v2`；v1 目录、项目、证据和结果保持只读。
- capability backtest 不调用 `add_equity`、`add_future`、`add_option`、`market_order`、`set_holdings`、brokerage 或 live API。
- Object Store 正式键包含项目 ID、`v2`、冻结 Git 提交、运行标签、算法 ID 和年份；已有键立即失败，禁止覆盖或删除。
- 1 KB UTF-8 字符串和 1 KB bytes 均须在云端写后读回，并由 Atlas 的 list/get API 再次获取和校验长度与 SHA-256。
- 若 bytes 失败但字符串成功，证据 transport 固定为 `base64-gzip-string`；若两者均失败，Phase A 为 `UNVERIFIED`，仅报告 Storage Create 权限或容量阻塞，不购买容量。
- 合成分年块只验证基础设施，不是策略收益证据；所有权益、PnL 和费用字段必须明确标记为 synthetic capability fixture。
- 任一保存、读回、list/get、下载、哈希、日期顺序、manifest、归因守恒或源码同步失败，Phase A 整体为 `UNVERIFIED`。
- 完成时必须保留原始 backtest 元数据、对象列表、原始下载文件、机器可读验证结果和中文能力报告。

## Execution setup: 建立 Phase A 独立 worktree

- [ ] **从已批准设计分支建立独立实施分支，不在设计分支直接写代码。**

Run:

```bash
git status --porcelain
git branch --show-current
git worktree add /home/jingtianyu/projects/spy-plus-10-v2-phase-a \
  -b feature/v2-phase-a-evidence feature/v2-robust-alpha-design
cd /home/jingtianyu/projects/spy-plus-10-v2-phase-a
git status --short --branch
```

Expected: 原 worktree clean；新 worktree 分支为 `feature/v2-phase-a-evidence`，起点包含已批准规范和本计划。

## Task 1: 建立 v2 项目边界与只证据模式

**Files:**
- Create: `spy_plus_10/v2_foundation.py`
- Create: `scripts/verify_v2_foundation.py`
- Create: `tests/test_v2_foundation.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward v2/config.json`（由 LEAN CLI 生成后保留其 ID 字段）
- Create: `qc-workspace/SPY Plus 10 Walk-Forward v2/project-manifest.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward v2/main.py`

- [ ] **先写失败测试，固定新项目名称、manifest 和禁止交易边界。**

```python
# tests/test_v2_foundation.py
import json
import tempfile
import unittest
from pathlib import Path

from spy_plus_10.v2_foundation import (
    V2FoundationError,
    validate_v2_foundation,
)


class V2FoundationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_repository_v2_foundation_is_valid(self):
        status = validate_v2_foundation(self.root)
        self.assertEqual(status.project_name, "SPY Plus 10 Walk-Forward v2")
        self.assertEqual(status.mode, "evidence-capability-smoke")
        self.assertFalse(status.live_trading)

    def test_live_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"
            project.mkdir(parents=True)
            (root / "qc-workspace" / "lean.json").write_text("{}", encoding="utf-8")
            (project / "config.json").write_text("{}", encoding="utf-8")
            manifest = {
                "benchmark": "NONE",
                "end_date": "2015-01-05",
                "formal_evaluation": False,
                "initial_cash": 1_000_000,
                "language": "Python",
                "live_trading": True,
                "mode": "evidence-capability-smoke",
                "name": "SPY Plus 10 Walk-Forward v2",
                "start_date": "2015-01-02",
            }
            (project / "project-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (project / "main.py").write_text(
                "class SpyPlusTenV2EvidenceCapability(QCAlgorithm):\n"
                "    def initialize(self):\n"
                "        return None\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(V2FoundationError, "manifest mismatch"):
                validate_v2_foundation(root)

    def test_order_and_brokerage_calls_are_rejected(self):
        source = (
            self.root
            / "qc-workspace"
            / "SPY Plus 10 Walk-Forward v2"
            / "main.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "add_equity(", "add_future(", "add_option(", "market_order(",
            "set_holdings(", "set_brokerage_model(", "set_live_mode(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **运行测试并确认因缺少模块/项目而失败。**

Run: `python -m unittest tests.test_v2_foundation -v`

Expected: `ModuleNotFoundError` 或 `missing required file`，且失败原因仅是 v2 foundation 尚未建立。

- [ ] **在 `qc-workspace` 中用当前 LEAN CLI 创建 Python 项目，不推送云端。**

Working directory: `/home/jingtianyu/projects/spy-plus-10-v2-phase-a/qc-workspace`

Run: `lean project-create "SPY Plus 10 Walk-Forward v2" --language python`

Expected: 新目录位于 `qc-workspace/SPY Plus 10 Walk-Forward v2/`；此步骤不得带 `cloud`、`--push` 或 `--force`。

- [ ] **写入精确 manifest。**

```json
{
  "benchmark": "NONE",
  "end_date": "2015-01-05",
  "formal_evaluation": false,
  "initial_cash": 1000000,
  "language": "Python",
  "live_trading": false,
  "mode": "evidence-capability-smoke",
  "name": "SPY Plus 10 Walk-Forward v2",
  "start_date": "2015-01-02"
}
```

- [ ] **实现独立 foundation validator；只检查 v2，不扩大 v1 validator 的职责。**

```python
# spy_plus_10/v2_foundation.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_NAME = "SPY Plus 10 Walk-Forward v2"
EXPECTED_MANIFEST = {
    "benchmark": "NONE",
    "end_date": "2015-01-05",
    "formal_evaluation": False,
    "initial_cash": 1_000_000,
    "language": "Python",
    "live_trading": False,
    "mode": "evidence-capability-smoke",
    "name": PROJECT_NAME,
    "start_date": "2015-01-02",
}
FORBIDDEN_SOURCE = (
    "add_equity(", "add_future(", "add_option(", "market_order(",
    "set_holdings(", "set_brokerage_model(", "set_live_mode(",
)


class V2FoundationError(RuntimeError):
    """Raised when the isolated v2 evidence project is unsafe or incomplete."""


@dataclass(frozen=True)
class V2FoundationStatus:
    project_name: str
    mode: str
    live_trading: bool


def _read_object(path: Path) -> dict:
    if not path.is_file():
        raise V2FoundationError(f"missing required file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V2FoundationError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise V2FoundationError(f"expected JSON object: {path}")
    return value


def validate_v2_foundation(root: Path) -> V2FoundationStatus:
    workspace = root.resolve() / "qc-workspace"
    project = workspace / PROJECT_NAME
    _read_object(workspace / "lean.json")
    _read_object(project / "config.json")
    manifest = _read_object(project / "project-manifest.json")
    if manifest != EXPECTED_MANIFEST:
        raise V2FoundationError("v2 project manifest mismatch")
    source_path = project / "main.py"
    if not source_path.is_file():
        raise V2FoundationError("missing required file: main.py")
    source = source_path.read_text(encoding="utf-8")
    required = (
        "class SpyPlusTenV2EvidenceCapability(QCAlgorithm):",
        "self.set_start_date(2015, 1, 2)",
        "self.set_end_date(2015, 1, 5)",
        "self.set_cash(1_000_000)",
        'self.get_parameter("v2_git_commit")',
        'self.get_parameter("evidence_run_label")',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise V2FoundationError(f"main.py missing markers: {missing}")
    present = [marker for marker in FORBIDDEN_SOURCE if marker in source]
    if present:
        raise V2FoundationError(f"v2 evidence project contains trading calls: {present}")
    return V2FoundationStatus(PROJECT_NAME, manifest["mode"], False)
```

```python
# scripts/verify_v2_foundation.py
#!/usr/bin/env python3
from pathlib import Path

from spy_plus_10.v2_foundation import validate_v2_foundation


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    status = validate_v2_foundation(root)
    print(f"V2_FOUNDATION_OK project={status.project_name} mode={status.mode}")
```

- [ ] **暂时把 LEAN starter `main.py` 改成只含固定日期、资金和运行参数读取的无交易入口；Task 4 再补齐 capability 写入。**

```python
# qc-workspace/SPY Plus 10 Walk-Forward v2/main.py
from AlgorithmImports import *


class SpyPlusTenV2EvidenceCapability(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 5)
        self.set_cash(1_000_000)
        self._git_commit = self.get_parameter("v2_git_commit")
        self._run_label = self.get_parameter("evidence_run_label")
```

- [ ] **运行 focused tests 和 validator。**

Run: `python -m unittest tests.test_v2_foundation -v && python scripts/verify_v2_foundation.py`

Expected: 3 tests pass；最后一行以 `V2_FOUNDATION_OK` 开头。

- [ ] **提交 Task 1。**

Run: `git add spy_plus_10/v2_foundation.py scripts/verify_v2_foundation.py tests/test_v2_foundation.py "qc-workspace/SPY Plus 10 Walk-Forward v2" && git commit -m "基础：建立 v2 证据能力项目"`

## Task 2: 实现确定性的分年证据与 manifest 协议

**Files:**
- Create: `spy_plus_10/v2/__init__.py`
- Create: `spy_plus_10/v2/evidence.py`
- Create: `tests/test_v2_evidence.py`

- [ ] **先写失败测试，覆盖键名、确定性 gzip、5 MB 上限、日期与 fallback。**

```python
# tests/test_v2_evidence.py
import gzip
import json
import unittest

from spy_plus_10.v2.evidence import (
    EvidenceError,
    build_chunk_key,
    build_manifest,
    build_manifest_key,
    decode_transport,
    encode_chunk,
    encode_string_transport,
    sha256_b64,
)


def daily_row(day: str) -> dict:
    return {
        "date": day,
        "strategy_equity": "1000000.00",
        "spy_equity": "1000000.00",
        "sleeves": {
            name: {"daily_pnl": "0", "cumulative_pnl": "0", "fees": "0", "slippage": "0"}
            for name in ("core", "equity", "futures", "defensive_option")
        },
        "positions": [], "cash": "1000000.00", "margin_used": "0",
        "margin_remaining": "1000000.00", "option_max_loss": "0",
        "total_gross": "0", "alpha_gross": "0", "beta": "0",
        "risk_contributions": {"core": "0", "equity": "0", "futures": "0"},
        "drawdown": "0", "drawdown_state": "NORMAL",
        "walk_forward": {"training_start": None, "training_end": None,
                         "execution_year": 2015, "selected_parameters": None,
                         "selection_reason": "SYNTHETIC_CAPABILITY_FIXTURE"},
        "chronology": {"data_cutoff": None, "signal_time": None,
                       "order_time": None, "fill_time": None},
        "gates": {"data_license": "NOT_APPLICABLE", "data_missing": 0,
                  "order_rejected": 0, "partial_fill": 0, "cancelled": 0,
                  "exercise": 0, "assignment": 0, "future_data": 0,
                  "failures": []},
    }


class V2EvidenceTests(unittest.TestCase):
    def test_key_contains_every_immutable_identity(self):
        commit = "a" * 40
        key = build_chunk_key(123, commit, "phase-a-capability", "algo-7", 2015)
        self.assertEqual(key, "123/v2/" + commit + "/phase-a-capability/algo-7/evidence/2015.jsonGz")
        self.assertTrue(build_manifest_key(123, commit, "phase-a-capability", "algo-7").endswith("/manifest.json"))

    def test_gzip_is_deterministic_and_round_trips(self):
        payload = {"schema_version": 2, "kind": "annual-evidence", "run_variant": "full", "year": 2015,
                   "synthetic": True, "daily": [daily_row("2015-01-02"), daily_row("2015-01-05")]}
        first = encode_chunk(payload)
        second = encode_chunk(payload)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(gzip.decompress(first)), payload)
        self.assertEqual(decode_transport(encode_string_transport(first)), first)

    def test_manifest_rejects_duplicate_year_and_oversized_chunk(self):
        item = {"year": 2015, "key": "k", "encoded_bytes": 5 * 1024 * 1024 + 1,
                "sha256": sha256_b64(b"x"), "first_date": "2015-01-02",
                "last_date": "2015-01-05", "rows": 2}
        with self.assertRaises(EvidenceError):
            build_manifest(123, "a" * 40, "phase-a-capability", "algo-7",
                           "full", "bytes", [item, item])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **运行并确认缺少 `spy_plus_10.v2.evidence`。**

Run: `python -m unittest tests.test_v2_evidence -v`

Expected: import failure。

- [ ] **实现纯 Python 协议，固定 transport 前缀为 `base64-gzip:`，SHA-256 用 base64 表示。**

Implementation contract for `spy_plus_10/v2/evidence.py`:

```python
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation


SCHEMA_VERSION = 2
MAX_CHUNK_BYTES = 5 * 1024 * 1024
SLEEVES = ("core", "equity", "futures", "defensive_option")
RUN_VARIANTS = (
    "full", "core_only", "equity_only", "futures_only", "defensive_option_only",
    "without_core", "without_equity", "without_futures", "without_defensive_option",
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STRING_PREFIX = "base64-gzip:"


class EvidenceError(RuntimeError):
    """Raised when v2 evidence is incomplete or internally inconsistent."""


def _identity(project_id, commit: str, run_label: str, algorithm_id: str) -> tuple[str, str, str, str]:
    values = (str(project_id), str(commit), str(run_label), str(algorithm_id))
    if not _IDENTIFIER.fullmatch(values[0]) or not _COMMIT.fullmatch(values[1]):
        raise EvidenceError("project or commit identity is invalid")
    if not _IDENTIFIER.fullmatch(values[2]) or not _IDENTIFIER.fullmatch(values[3]):
        raise EvidenceError("run or algorithm identity is invalid")
    return values


def _prefix(project_id, commit: str, run_label: str, algorithm_id: str) -> str:
    project, frozen, label, algorithm = _identity(project_id, commit, run_label, algorithm_id)
    return f"{project}/v2/{frozen}/{label}/{algorithm}"


def build_probe_keys(project_id, commit: str, run_label: str, algorithm_id: str) -> dict[str, str]:
    prefix = _prefix(project_id, commit, run_label, algorithm_id)
    return {"string": f"{prefix}/capability/string-1kb.txt", "bytes": f"{prefix}/capability/bytes-1kb.bin"}


def build_chunk_key(project_id, commit: str, run_label: str, algorithm_id: str, year: int) -> str:
    if not 2015 <= int(year) <= 2100:
        raise EvidenceError("evidence year is invalid")
    return f"{_prefix(project_id, commit, run_label, algorithm_id)}/evidence/{int(year)}.jsonGz"


def build_manifest_key(project_id, commit: str, run_label: str, algorithm_id: str) -> str:
    return f"{_prefix(project_id, commit, run_label, algorithm_id)}/manifest.json"


def canonical_json_bytes(value: dict) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise EvidenceError("evidence is not JSON serializable") from error


def sha256_b64(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


def _decimal(value, label: str, *, positive: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise EvidenceError(f"{label} is not numeric") from error
    if not number.is_finite() or (positive and number <= 0):
        raise EvidenceError(f"{label} is invalid")
    return number


def validate_daily_row(row: dict, expected_year: int) -> date:
    required = {"date", "strategy_equity", "spy_equity", "sleeves", "positions", "cash",
                "margin_used", "margin_remaining", "option_max_loss", "total_gross",
                "alpha_gross", "beta", "risk_contributions", "drawdown", "drawdown_state",
                "walk_forward", "chronology", "gates"}
    if not isinstance(row, dict) or not required.issubset(row):
        raise EvidenceError("daily evidence row is incomplete")
    try:
        current = date.fromisoformat(row["date"])
    except (TypeError, ValueError) as error:
        raise EvidenceError("daily evidence date is invalid") from error
    if current.year != expected_year:
        raise EvidenceError("daily evidence crosses year boundary")
    _decimal(row["strategy_equity"], "strategy equity", positive=True)
    _decimal(row["spy_equity"], "SPY equity", positive=True)
    sleeves = row["sleeves"]
    if not isinstance(sleeves, dict) or tuple(sorted(sleeves)) != tuple(sorted(SLEEVES)):
        raise EvidenceError("daily sleeve set is incomplete")
    for name in SLEEVES:
        if set(sleeves[name]) != {"daily_pnl", "cumulative_pnl", "fees", "slippage"}:
            raise EvidenceError(f"daily sleeve fields are invalid: {name}")
        for field, value in sleeves[name].items():
            _decimal(value, f"{name}.{field}")
    if not isinstance(row["positions"], list) or not isinstance(row["gates"].get("failures"), list):
        raise EvidenceError("positions or gate failures are invalid")
    return current


def validate_chunk(payload: dict) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceError("evidence schema version is invalid")
    if payload.get("kind") != "annual-evidence" or payload.get("synthetic") not in {True, False}:
        raise EvidenceError("evidence kind is invalid")
    if payload.get("run_variant") not in RUN_VARIANTS:
        raise EvidenceError("evidence run variant is invalid")
    year = payload.get("year")
    if not isinstance(year, int):
        raise EvidenceError("evidence year is missing")
    daily = payload.get("daily")
    if not isinstance(daily, list) or not daily:
        raise EvidenceError("daily evidence is missing")
    dates = [validate_daily_row(row, year) for row in daily]
    if any(current <= previous for previous, current in zip(dates, dates[1:])):
        raise EvidenceError("daily dates must be strictly increasing")


def encode_chunk(payload: dict) -> bytes:
    validate_chunk(payload)
    return gzip.compress(canonical_json_bytes(payload), compresslevel=9, mtime=0)


def encode_string_transport(value: bytes) -> str:
    return _STRING_PREFIX + base64.b64encode(value).decode("ascii")


def decode_transport(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str) or not value.startswith(_STRING_PREFIX):
        raise EvidenceError("string transport prefix is invalid")
    try:
        return base64.b64decode(value[len(_STRING_PREFIX):], validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError("string transport base64 is invalid") from error


def chunk_descriptor(year: int, key: str, encoded: bytes, daily: list[dict]) -> dict:
    return {"year": int(year), "key": str(key), "encoded_bytes": len(encoded),
            "sha256": sha256_b64(encoded), "first_date": daily[0]["date"],
            "last_date": daily[-1]["date"], "rows": len(daily)}


def build_manifest(project_id, commit: str, run_label: str, algorithm_id: str,
                   run_variant: str, transport: str, chunks: list[dict]) -> dict:
    project, frozen, label, algorithm = _identity(project_id, commit, run_label, algorithm_id)
    if run_variant not in RUN_VARIANTS:
        raise EvidenceError("manifest run variant is invalid")
    if transport not in {"bytes", "base64-gzip-string"} or not chunks:
        raise EvidenceError("manifest transport or chunks are invalid")
    years = [item.get("year") for item in chunks]
    keys = [item.get("key") for item in chunks]
    if len(years) != len(set(years)) or len(keys) != len(set(keys)):
        raise EvidenceError("manifest contains duplicate years or keys")
    for item in chunks:
        if item.get("encoded_bytes", 0) <= 0 or item["encoded_bytes"] > MAX_CHUNK_BYTES:
            raise EvidenceError("evidence chunk exceeds size limit")
    return {"schema_version": SCHEMA_VERSION, "kind": "evidence-manifest",
            "project_id": project, "version": "v2", "frozen_commit": frozen,
            "run_label": label, "algorithm_id": algorithm, "run_variant": run_variant,
            "transport": transport,
            "chunks": sorted(chunks, key=lambda item: item["year"])}
```

- [ ] **运行 focused tests。**

Run: `python -m unittest tests.test_v2_evidence -v`

Expected: 3 tests pass。

- [ ] **提交 Task 2。**

Run: `git add spy_plus_10/v2 tests/test_v2_evidence.py && git commit -m "功能：增加 v2 分块证据协议"`

## Task 3: 建立日度 sleeve PnL 与 ablation 数据接口

**Files:**
- Create: `spy_plus_10/v2/attribution.py`
- Create: `tests/test_v2_attribution.py`

- [ ] **先写失败测试，固定四个 sleeve、费用归属、组合守恒和九个独立 component/ablation 运行变体。**

```python
# tests/test_v2_attribution.py
import unittest
from decimal import Decimal

from spy_plus_10.v2.attribution import (
    ABLATION_VARIANTS,
    AttributionError,
    RUN_VARIANTS,
    SleeveLedger,
    enabled_sleeves,
)


class V2AttributionTests(unittest.TestCase):
    def test_daily_pnl_reconciles_to_equity_change_after_external_flow(self):
        ledger = SleeveLedger(initial_equity="1000000")
        ledger.record_day("2015-01-02", {"core": "600000", "equity": "150000",
                          "futures": "100000", "defensive_option": "0"},
                          cash="150000", external_flow="0", fees={}, slippage={})
        row = ledger.record_day("2015-01-05", {"core": "606000", "equity": "148000",
                          "futures": "101000", "defensive_option": "0"},
                          cash="200000", external_flow="50000",
                          fees={"equity": "25"}, slippage={"futures": "10"})
        self.assertEqual(row["portfolio_daily_pnl"], Decimal("5000"))
        self.assertEqual(sum(row["sleeve_daily_pnl"].values()), Decimal("5000"))
        self.assertEqual(row["fees"]["equity"], Decimal("25"))
        self.assertEqual(row["slippage"]["futures"], Decimal("10"))

    def test_component_and_ablation_variants_are_fixed(self):
        self.assertEqual(len(ABLATION_VARIANTS), 9)
        self.assertEqual(tuple(ABLATION_VARIANTS), RUN_VARIANTS)
        self.assertEqual(enabled_sleeves("full"),
                         ("core", "equity", "futures", "defensive_option"))
        self.assertEqual(enabled_sleeves("without_core"),
                         ("equity", "futures", "defensive_option"))
        self.assertEqual(enabled_sleeves("equity_only"), ("equity",))

    def test_disabled_sleeve_exposure_fails_closed(self):
        ledger = SleeveLedger(initial_equity="100", run_variant="without_futures")
        with self.assertRaisesRegex(AttributionError, "disabled sleeve"):
            ledger.record_day("2015-01-02", {"core": "90", "equity": "0",
                              "futures": "5", "defensive_option": "0"},
                              cash="5", external_flow="0", fees={}, slippage={})

    def test_missing_sleeve_fails_closed(self):
        ledger = SleeveLedger(initial_equity="100")
        with self.assertRaises(AttributionError):
            ledger.record_day("2015-01-02", {"core": "100"}, cash="0",
                              external_flow="0", fees={}, slippage={})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **运行测试，确认 import failure。**

Run: `python -m unittest tests.test_v2_attribution -v`

- [ ] **实现 Decimal ledger；PnL 定义必须包括每个 sleeve 的标记价值变化、已归属现金流和费用，不允许剩余差额静默进入 `other`。**

Required public interface in `spy_plus_10/v2/attribution.py`:

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from .evidence import RUN_VARIANTS, SLEEVES


ABLATION_VARIANTS = {
    "full": SLEEVES,
    "core_only": ("core",),
    "equity_only": ("equity",),
    "futures_only": ("futures",),
    "defensive_option_only": ("defensive_option",),
    "without_core": ("equity", "futures", "defensive_option"),
    "without_equity": ("core", "futures", "defensive_option"),
    "without_futures": ("core", "equity", "defensive_option"),
    "without_defensive_option": ("core", "equity", "futures"),
}


class AttributionError(RuntimeError):
    """Raised when sleeve attribution cannot reconcile exactly."""


def _d(value, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AttributionError(f"{label} is not numeric") from error
    if not result.is_finite():
        raise AttributionError(f"{label} is not finite")
    return result


def enabled_sleeves(run_variant: str) -> tuple[str, ...]:
    try:
        return tuple(ABLATION_VARIANTS[run_variant])
    except KeyError as error:
        raise AttributionError("unknown component or ablation variant") from error


class SleeveLedger:
    def __init__(self, initial_equity, run_variant: str = "full") -> None:
        self._initial_equity = _d(initial_equity, "initial equity")
        if self._initial_equity <= 0:
            raise AttributionError("initial equity must be positive")
        self._run_variant = run_variant
        self._enabled = enabled_sleeves(run_variant)
        self._last_date = None
        self._last_values = None
        self._last_cash = None
        self._rows = []
        self._cumulative = {name: Decimal("0") for name in SLEEVES}

    @staticmethod
    def _mapping(values, label: str, default_zero: bool = False):
        if not isinstance(values, dict):
            raise AttributionError(f"{label} must be a mapping")
        if not default_zero and set(values) != set(SLEEVES):
            raise AttributionError(f"{label} must contain exactly four sleeves")
        unknown = set(values) - set(SLEEVES)
        if unknown:
            raise AttributionError(f"{label} contains unknown sleeves")
        return {name: _d(values.get(name, 0), f"{label}.{name}") for name in SLEEVES}

    def record_day(self, day: str, marked_values: dict, *, cash, external_flow,
                   fees: dict, slippage: dict, sleeve_cash_flows: dict | None = None) -> dict:
        current_date = date.fromisoformat(day)
        if self._last_date is not None and current_date <= self._last_date:
            raise AttributionError("ledger dates must be strictly increasing")
        current = self._mapping(marked_values, "marked values")
        current_cash = _d(cash, "cash")
        flow = _d(external_flow, "external flow")
        fee_map = self._mapping(fees, "fees", True)
        slip_map = self._mapping(slippage, "slippage", True)
        flow_map = self._mapping(sleeve_cash_flows or {}, "sleeve cash flows", True)
        for name in set(SLEEVES) - set(self._enabled):
            if any(value != 0 for value in (current[name], fee_map[name], slip_map[name], flow_map[name])):
                raise AttributionError(f"disabled sleeve has exposure or cost: {name}")
        equity = current_cash + sum(current.values())
        if self._last_values is None:
            if equity - flow != self._initial_equity:
                raise AttributionError("opening ledger does not match initial equity")
            daily = {name: Decimal("0") for name in SLEEVES}
            portfolio_pnl = Decimal("0")
        else:
            prior_equity = self._last_cash + sum(self._last_values.values())
            portfolio_pnl = equity - prior_equity - flow
            daily = {name: current[name] - self._last_values[name] - flow_map[name]
                     for name in SLEEVES}
            residual = portfolio_pnl - sum(daily.values())
            daily["core"] += residual
            if sum(daily.values()) != portfolio_pnl:
                raise AttributionError("sleeve PnL does not reconcile")
        for name in SLEEVES:
            self._cumulative[name] += daily[name]
        row = {"date": day, "run_variant": self._run_variant,
               "enabled_sleeves": self._enabled, "equity": equity, "external_flow": flow,
               "portfolio_daily_pnl": portfolio_pnl, "sleeve_daily_pnl": daily,
               "sleeve_cumulative_pnl": dict(self._cumulative),
               "fees": fee_map, "slippage": slip_map}
        self._rows.append(row)
        self._last_date, self._last_values, self._last_cash = current_date, current, current_cash
        return row

    def equity_path(self) -> list[Decimal]:
        return [row["equity"] for row in self._rows]
```

Implementation notes:

- `core` receives only the explicitly calculated unallocated cash residual because cash is owned by the core/cash sleeve. Add a fixture proving this convention; if later modules need separate sleeve cash accounts, Phase B must change the evidence schema under a new schema version rather than silently changing this accounting rule。
- ablation 必须是独立运行变体，不能用 `full PnL - sleeve PnL` 伪造，因为移除模块会改变风险缩放、现金和交易路径。Phase C 将分别运行 `without_*`，独立 verifier 只比较各自真实权益曲线。

- [ ] **运行 focused tests。**

Run: `python -m unittest tests.test_v2_attribution -v`

Expected: 4 tests pass。

- [ ] **提交 Task 3。**

Run: `git add spy_plus_10/v2/attribution.py tests/test_v2_attribution.py && git commit -m "功能：增加 v2 日度归因与消融接口"`

## Task 4: 同步纯模块并完成无交易 capability algorithm

**Files:**
- Create: `scripts/sync_v2_cloud_modules.py`
- Create: `tests/test_v2_cloud_sync.py`
- Modify: `qc-workspace/SPY Plus 10 Walk-Forward v2/main.py`
- Create/Sync: `qc-workspace/SPY Plus 10 Walk-Forward v2/evidence.py`
- Create/Sync: `qc-workspace/SPY Plus 10 Walk-Forward v2/attribution.py`

- [ ] **先写同步失败测试，要求云端 copies 与 canonical files 字节完全相同。**

```python
# tests/test_v2_cloud_sync.py
import unittest
from pathlib import Path


class V2CloudSyncTests(unittest.TestCase):
    def test_cloud_pure_modules_match_canonical_sources(self):
        root = Path(__file__).resolve().parents[1]
        cloud = root / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"
        canonical = root / "spy_plus_10" / "v2"
        for name in ("evidence.py", "attribution.py"):
            self.assertEqual((cloud / name).read_bytes(), (canonical / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **运行并确认因 cloud copies 缺失而失败。**

Run: `python -m unittest tests.test_v2_cloud_sync -v`

- [ ] **实现单向同步脚本；禁止从 cloud copy 回写 canonical source。**

```python
# scripts/sync_v2_cloud_modules.py
#!/usr/bin/env python3
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "spy_plus_10" / "v2"
TARGET = ROOT / "qc-workspace" / "SPY Plus 10 Walk-Forward v2"


if __name__ == "__main__":
    for name in ("evidence.py", "attribution.py"):
        shutil.copyfile(SOURCE / name, TARGET / name)
        print(f"SYNCED {name}")
```

- [ ] **运行同步，并把 cloud imports 从相对导入改为兼容顶层导入。**

Before syncing, change canonical `attribution.py` import to:

```python
try:
    from .evidence import RUN_VARIANTS, SLEEVES
except ImportError:
    from evidence import RUN_VARIANTS, SLEEVES
```

Run: `python scripts/sync_v2_cloud_modules.py`

- [ ] **实现 capability algorithm：写前检查不存在；字符串和 bytes 分别 try/read/hash；bytes 失败时只回退证据块 transport，不把 bytes probe 伪装成成功。**

Required `main.py` behavior:

```python
from AlgorithmImports import *
import json

from evidence import (
    build_chunk_key, build_manifest, build_manifest_key, build_probe_keys,
    canonical_json_bytes, chunk_descriptor, encode_chunk,
    encode_string_transport, sha256_b64,
)


class SpyPlusTenV2EvidenceCapability(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 5)
        self.set_cash(1_000_000)
        self._git_commit = self.get_parameter("v2_git_commit")
        self._run_label = self.get_parameter("evidence_run_label")
        self._algorithm = str(self.algorithm_id)
        self._project = str(self.project_id)
        self._status = {"string": "UNVERIFIED", "bytes": "UNVERIFIED",
                        "chunk": "UNVERIFIED", "manifest": "UNVERIFIED"}
        self._run_capability_smoke()

    def _save_unique_string(self, key: str, value: str) -> None:
        if self.object_store.contains_key(key):
            raise RuntimeError(f"OBJECT_STORE_KEY_EXISTS:{key}")
        if not self.object_store.save(key, value) or self.object_store.read(key) != value:
            raise RuntimeError(f"OBJECT_STORE_STRING_ROUND_TRIP_FAILED:{key}")

    def _save_unique_bytes(self, key: str, value: bytes) -> None:
        if self.object_store.contains_key(key):
            raise RuntimeError(f"OBJECT_STORE_KEY_EXISTS:{key}")
        if not self.object_store.save_bytes(key, value) or bytes(self.object_store.read_bytes(key)) != value:
            raise RuntimeError(f"OBJECT_STORE_BYTES_ROUND_TRIP_FAILED:{key}")

    def _synthetic_row(self, day: str) -> dict:
        sleeves = {name: {"daily_pnl": "0", "cumulative_pnl": "0", "fees": "0", "slippage": "0"}
                   for name in ("core", "equity", "futures", "defensive_option")}
        return {"date": day, "strategy_equity": "1000000.00", "spy_equity": "1000000.00",
                "sleeves": sleeves, "positions": [], "cash": "1000000.00",
                "margin_used": "0", "margin_remaining": "1000000.00",
                "option_max_loss": "0", "total_gross": "0", "alpha_gross": "0",
                "beta": "0", "risk_contributions": {"core": "0", "equity": "0", "futures": "0"},
                "drawdown": "0", "drawdown_state": "NORMAL",
                "walk_forward": {"training_start": None, "training_end": None,
                    "execution_year": 2015, "selected_parameters": None,
                    "selection_reason": "SYNTHETIC_CAPABILITY_FIXTURE"},
                "chronology": {"data_cutoff": None, "signal_time": None,
                    "order_time": None, "fill_time": None},
                "gates": {"data_license": "NOT_APPLICABLE", "data_missing": 0,
                    "order_rejected": 0, "partial_fill": 0, "cancelled": 0,
                    "exercise": 0, "assignment": 0, "future_data": 0, "failures": []}}

    def _run_capability_smoke(self) -> None:
        probes = build_probe_keys(self._project, self._git_commit, self._run_label, self._algorithm)
        chunk_key = build_chunk_key(self._project, self._git_commit, self._run_label, self._algorithm, 2015)
        manifest_key = build_manifest_key(self._project, self._git_commit, self._run_label, self._algorithm)
        for key in (*probes.values(), chunk_key, manifest_key):
            if self.object_store.contains_key(key):
                raise RuntimeError(f"OBJECT_STORE_KEY_EXISTS:{key}")
        string_value = "S" * 1024
        bytes_value = bytes(index % 251 for index in range(1024))
        self._save_unique_string(probes["string"], string_value)
        self._status["string"] = "PASS"
        try:
            self._save_unique_bytes(probes["bytes"], bytes_value)
            self._status["bytes"] = "PASS"
            transport = "bytes"
        except Exception as error:
            if str(error).startswith("OBJECT_STORE_KEY_EXISTS:"):
                raise
            self._status["bytes"] = "FAIL"
            self.debug(f"BYTES_PROBE_FAILED:{type(error).__name__}")
            transport = "base64-gzip-string"
        daily = [self._synthetic_row("2015-01-02"), self._synthetic_row("2015-01-05")]
        payload = {"schema_version": 2, "kind": "annual-evidence", "run_variant": "full", "year": 2015,
                   "synthetic": True, "daily": daily}
        encoded = encode_chunk(payload)
        if transport == "bytes":
            self._save_unique_bytes(chunk_key, encoded)
        else:
            self._save_unique_string(chunk_key, encode_string_transport(encoded))
        self._status["chunk"] = "PASS"
        descriptor = chunk_descriptor(2015, chunk_key, encoded, daily)
        manifest = build_manifest(self._project, self._git_commit, self._run_label,
                                  self._algorithm, "full", transport, [descriptor])
        self._save_unique_string(manifest_key, canonical_json_bytes(manifest).decode("utf-8"))
        self._status["manifest"] = "PASS"
        self.set_runtime_statistic("V2_EVIDENCE_PREFIX", chunk_key.rsplit("/evidence/", 1)[0])
        self.set_runtime_statistic("V2_MANIFEST_KEY", manifest_key)
        self.set_runtime_statistic("V2_STRING_KEY", probes["string"])
        self.set_runtime_statistic("V2_BYTES_KEY", probes["bytes"])
        self.set_runtime_statistic("V2_STRING_SHA256", sha256_b64(string_value.encode("utf-8")))
        self.set_runtime_statistic("V2_BYTES_SHA256", sha256_b64(bytes_value))
        self.set_runtime_statistic("V2_TRANSPORT", transport)

    def on_end_of_algorithm(self) -> None:
        required = (self._status["string"], self._status["chunk"], self._status["manifest"])
        overall = "UNVERIFIED"
        if all(value == "PASS" for value in required):
            overall = "PASS" if self._status["bytes"] == "PASS" else "PASS_WITH_STRING_FALLBACK"
        self.set_runtime_statistic("V2_CAPABILITY_STATUS", overall)
        for key, value in self._status.items():
            self.set_runtime_statistic(f"V2_{key.upper()}_STATUS", value)
```

- [ ] **增加 source-contract tests，断言 synthetic marker、唯一键检查、runtime statistics 存在，且所有交易调用仍缺席。**

Run: `python -m unittest tests.test_v2_cloud_sync tests.test_v2_foundation tests.test_v2_evidence -v && python scripts/verify_v2_foundation.py`

Expected: 全部通过。

- [ ] **提交 Task 4。**

Run: `git add scripts/sync_v2_cloud_modules.py tests/test_v2_cloud_sync.py spy_plus_10/v2/attribution.py "qc-workspace/SPY Plus 10 Walk-Forward v2" && git commit -m "功能：完成 Object Store 能力烟雾测试"`

## Task 5: 强化 QuantConnect 分页读取并增加 Object Store list API

**Files:**
- Modify: `scripts/fetch_quantconnect_evidence.py`
- Modify: `tests/test_fetch_quantconnect_evidence.py`

- [ ] **先写失败测试，重现 API 暂时返回 `status=loading`、list 分页和终态缺少 rows。**

Add these tests:

```python
def test_loading_backtest_rows_are_polled_before_pagination(self):
    client = QuantConnectClient("123", "secret", session=Mock(), sleep=lambda _: None)
    client._post_json = Mock(side_effect=[
        {"success": True, "status": "loading", "progress": 0.5},
        {"success": True, "status": "completed", "orders": [{"id": 1}]},
    ])
    self.assertEqual(client.read_all_backtest_rows(
        "backtests/orders/read", "orders", 1, "bt"), [{"id": 1}])

def test_terminal_response_without_rows_is_rejected(self):
    client = QuantConnectClient("123", "secret", session=Mock(), sleep=lambda _: None)
    client._post_json = Mock(return_value={"success": True, "status": "completed"})
    with self.assertRaises(QuantConnectApiError):
        client.read_all_backtest_rows("backtests/orders/read", "orders", 1, "bt")

def test_object_list_reads_all_pages(self):
    client = QuantConnectClient("123", "secret", session=Mock())
    client._post_json = Mock(side_effect=[
        {"success": True, "page": 1, "totalPages": 2, "objects": [{"key": "a"}]},
        {"success": True, "page": 2, "totalPages": 2, "objects": [{"key": "b"}],
         "objectStorageUsed": 2048},
    ])
    result = client.list_objects("org", "123/v2")
    self.assertEqual([item["key"] for item in result["objects"]], ["a", "b"])
    self.assertEqual(result["object_storage_used"], 2048)
```

- [ ] **运行并确认新测试失败。**

Run: `python -m unittest tests.test_fetch_quantconnect_evidence -v`

- [ ] **注入 sleep、为 rows 增加最多 30 次轮询，并按官方 `/object/list` 的 `page/totalPages` 模型分页。**

Required changes:

```python
class QuantConnectClient:
    def __init__(self, user_id: str, api_token: str, *, session=None, sleep=time.sleep):
        self._user_id = str(user_id)
        self._api_token = str(api_token)
        self._session = session or _UrllibSession()
        self._sleep = sleep

    def _read_rows_page(self, endpoint: str, field: str, payload: dict) -> list[dict]:
        for attempt in range(30):
            result = self._post_json(endpoint, payload)
            page = result.get(field)
            if isinstance(page, list):
                return page
            if result.get("status") == "loading" and attempt < 29:
                self._sleep(1)
                continue
            raise QuantConnectApiError(f"QuantConnect {field} response is invalid")
        raise QuantConnectApiError(f"QuantConnect {field} response timed out")

    def list_objects(self, organization_id: str, path: str) -> dict:
        objects = []
        page = 1
        total_pages = 1
        used = None
        while page <= total_pages:
            result = self._post_json("object/list", {
                "organizationId": str(organization_id), "path": str(path), "page": page
            })
            values = result.get("objects")
            if not isinstance(values, list):
                raise QuantConnectApiError("Object Store list response is invalid")
            objects.extend(values)
            total_pages = int(result.get("totalPages", 1))
            used = result.get("objectStorageUsed", used)
            page += 1
        return {"objects": objects, "object_storage_used": used}
```

Change `read_all_backtest_rows` to call `_read_rows_page` for each page. Change `download_object` polling from `time.sleep(1)` to `self._sleep(1)` so unit tests remain deterministic.

- [ ] **运行 v1 regression tests。**

Run: `python -m unittest tests.test_fetch_quantconnect_evidence tests.test_frozen_evaluation -v`

Expected: 现有 v1 tests 与新增 tests 全部通过。

- [ ] **提交 Task 5。**

Run: `git add scripts/fetch_quantconnect_evidence.py tests/test_fetch_quantconnect_evidence.py && git commit -m "修复：稳健读取 QuantConnect 分页结果"`

## Task 6: 建立 v2 下载器与独立验证器

**Files:**
- Create: `spy_plus_10/v2/verifier.py`
- Create: `scripts/fetch_v2_evidence.py`
- Create: `scripts/verify_v2_evidence.py`
- Create: `tests/test_v2_verifier.py`
- Create: `tests/test_fetch_v2_evidence.py`

- [ ] **先写失败 fixtures，至少覆盖 bytes PASS、string fallback PASS、缺对象、哈希错、日期错、sleeve 不守恒。**

The fixture builder must create:

```python
archive = {
    "backtest": {"statistics": {
        "V2_CAPABILITY_STATUS": "PASS",
        "V2_TRANSPORT": "bytes",
        "V2_STRING_KEY": string_key,
        "V2_BYTES_KEY": bytes_key,
        "V2_MANIFEST_KEY": manifest_key,
    }},
    "object_list": {"objects": [
        {"key": string_key, "size": 1024},
        {"key": bytes_key, "size": 1024},
        {"key": chunk_key, "size": len(chunk_bytes)},
        {"key": manifest_key, "size": len(manifest_bytes)},
    ], "object_storage_used": 4096},
    "orders": [],
    "trades": [],
    "objects": {
        string_key: b"S" * 1024,
        bytes_key: bytes(index % 251 for index in range(1024)),
        chunk_key: chunk_bytes,
        manifest_key: manifest_bytes,
    },
}
```

Assertions:

```python
result = verify_archive(archive)
self.assertEqual(result["overall_status"], "PASS")
self.assertEqual(result["object_store"]["string_round_trip"], "PASS")
self.assertEqual(result["object_store"]["bytes_round_trip"], "PASS")
self.assertEqual(result["attribution"]["reconciliation"], "PASS")
```

- [ ] **运行并确认 import failures。**

Run: `python -m unittest tests.test_v2_verifier tests.test_fetch_v2_evidence -v`

- [ ] **实现 verifier，禁止导入 `qc-workspace/SPY Plus 10 Walk-Forward v2/main.py`，并机械产生 `PASS|UNVERIFIED`。**

Required public functions in `spy_plus_10/v2/verifier.py` are `extract_runtime_statistics(backtest)`, `decode_manifest(raw)`, `verify_probe(name, raw, expected_size, expected_sha256)`, `verify_chunk(raw_transport, transport, descriptor)`, `recompute_attribution(daily)`, and `verify_archive(archive)`. Every function returns JSON-serializable dictionaries/values; it must not return `Decimal`, `date` or raw bytes across the public boundary.

Exact rules:

1. runtime stats 必须给出 string/bytes/manifest keys、transport 和 capability status；
2. bytes status 为 PASS 时，object list 中 string、bytes、chunk、manifest 四个必需 key 必须各出现一次；string fallback 时 bytes key 可不存在，其余三个必须各出现一次；
3. probes 必须精确为 canonical 1024-byte fixtures，且匹配 runtime SHA-256；
4. manifest identity、transport、chunk 唯一性和所有 descriptor 必须通过 `evidence.py` 的格式约束；
5. 每个 chunk 下载内容先按 manifest transport 解码，再与 descriptor 的 encoded bytes/SHA-256 比较；
6. gzip JSON 解码后再次 `validate_chunk`；first/last/rows 必须与 manifest 相同；
7. 对相邻 daily rows，独立复算权益变化；四 sleeve daily PnL 之和必须等于策略权益变化，所有费用和滑点保留分项；
8. capability synthetic fixture 必须为 2015-01-02 与 2015-01-05 两行、权益均为 1,000,000、无持仓、无 gate failure；
9. capability archive 的完整分页 orders/trades 必须均为 0；非零即安全失败并使 overall 为 `UNVERIFIED`；
10. bytes probe failure 可在 transport 为 `base64-gzip-string` 时保留为 `FAIL`，但 string、chunk、manifest 和 API 校验全部通过后 overall 为 `PASS_WITH_STRING_FALLBACK`；对 Phase A 完成判定将该状态视为 capability PASS；
11. 任一其他错误收集为稳定的 error code，overall 为 `UNVERIFIED`，不抛出后丢失其余诊断。

- [ ] **实现下载器，先创建临时目录，全部校验成功后才原子改名为目标目录；目标已存在时拒绝覆盖。**

CLI contract:

```text
python scripts/fetch_v2_evidence.py \
  --project-id "$V2_PROJECT_ID" \
  --backtest-id "$V2_BACKTEST_ID" \
  --organization-id "$V2_ORGANIZATION_ID" \
  --output-dir docs/evidence/v2-phase-a/capability
```

Downloader steps:

1. `read_backtest`；
2. 通过现有分页 client 读取全部 orders 和 trades；capability run 预期两者均为空；
3. 从 runtime statistics 读取 prefix、三个 probe/manifest keys；
4. `list_objects(organization_id, prefix)` 并保存完整 metadata；
5. 下载 string、bytes、manifest；
6. 解析 manifest 后下载每个 chunk；
7. 写 `backtest.json`、`orders.jsonl`、`trades.jsonl`、`object-list.json`、按下载顺序编号的 `objects/0001.bin` 等原始文件、`key-map.json`、`fetch-manifest.json`；
8. `fetch-manifest.json` 记录项目/算法/backtest/组织 ID、order/trade counts、每个原始 key、bytes、SHA-256 和下载 UTC 时间；
9. 不打印 user ID、token、Authorization、下载签名 URL 或 credentials 内容。

- [ ] **实现 `scripts/verify_v2_evidence.py`，读取 archive、调用 `verify_archive`，写 JSON 到指定路径并用 exit 0/1 表示 PASS/非 PASS。**

CLI contract:

```text
python scripts/verify_v2_evidence.py \
  --archive docs/evidence/v2-phase-a/capability \
  --output docs/evidence/v2-phase-a/capability/verification.json
```

- [ ] **运行 focused tests。**

Run: `python -m unittest tests.test_v2_evidence tests.test_v2_attribution tests.test_v2_verifier tests.test_fetch_v2_evidence -v`

Expected: 全部通过，错误 fixtures 返回 `UNVERIFIED` 而不是假 PASS。

- [ ] **提交 Task 6。**

Run: `git add spy_plus_10/v2 scripts/fetch_v2_evidence.py scripts/verify_v2_evidence.py tests/test_v2_verifier.py tests/test_fetch_v2_evidence.py && git commit -m "功能：增加 v2 证据下载与独立验证"`

## Task 7: 冻结 capability 源码并建立私有远端检查点

**Files:**
- Modify only if verification exposes a defect: files introduced in Tasks 1–6

- [ ] **运行完整本地套件，不因 v2 新增而破坏 v1。**

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q spy_plus_10 scripts "qc-workspace/SPY Plus 10 Walk-Forward v2"
python scripts/verify_cloud_foundation.py
python scripts/verify_audit_baseline.py
python scripts/verify_v2_foundation.py
python scripts/sync_v2_cloud_modules.py
git diff --exit-code -- "qc-workspace/SPY Plus 10 Walk-Forward v2/evidence.py" "qc-workspace/SPY Plus 10 Walk-Forward v2/attribution.py"
```

Expected: tests 全绿；三个 verifier 输出 OK；sync 后无 diff。

- [ ] **检查 scope 和敏感内容；不得把 LEAN credentials、Object Store signed URL、浏览器 cookies 或 API headers 加入 Git。**

Run:

```bash
git status --short
git diff --check
git diff --stat main...HEAD
rg --pcre2 -n '(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])' \
  --glob '!docs/evidence/**' --glob '!.git/**' .
```

Expected: 仅 Phase A 文件；`git diff --check` 无输出；64 位十六进制凭据模式搜索无输出。证据哈希固定使用 base64，因此不需要放宽此门禁。

- [ ] **若最后一次验证修复产生未提交变更，创建独立检查点。**

Run `git status --short`, then add each modified Task 1–6 file by its exact path and commit with `git commit -m "测试：冻结 v2 证据能力实现"`. 不使用 `git add .`，避免带入无关改动。

- [ ] **验证精确 GitHub 远端为 private，然后推送当前 feature branch。**

Run:

```bash
git remote get-url origin
gh repo view Jimmyyu725/spy-plus-10-walk-forward --json visibility,nameWithOwner
git push -u origin feature/v2-phase-a-evidence
git rev-parse HEAD
git ls-remote origin refs/heads/feature/v2-phase-a-evidence
```

Expected: `visibility` 为 `PRIVATE`；本地 HEAD 与远端 branch hash 完全相同。

- [ ] **记录 capability commit，但不把该值写入源码。**

Run:

```bash
V2_CAPABILITY_COMMIT=$(git rev-parse HEAD)
test -n "$V2_CAPABILITY_COMMIT"
git status --porcelain
```

Expected: worktree clean；变量为 40 位 commit。

## Task 8: 新建云端 v2 项目并运行一次 capability backtest

**Files:**
- QuantConnect Cloud project: `SPY Plus 10 Walk-Forward v2`
- No repository file changes before the backtest completes

- [ ] **确认 CLI 登录组织、现有云端项目和本地 config 映射；不得使用 `--force`。**

Run:

```bash
lean whoami
python -c 'import json; from pathlib import Path; p=Path("qc-workspace/SPY Plus 10 Walk-Forward v2/config.json"); print({k:v for k,v in json.loads(p.read_text()).items() if k in {"local-id","cloud-id","organization-id"}})'
python - <<'PY'
from pathlib import Path
from scripts.fetch_quantconnect_evidence import QuantConnectClient, load_credentials

user_id, token = load_credentials(Path("/home/jingtianyu/.lean/credentials"))
client = QuantConnectClient(user_id, token)
result = client._post_json("projects/read", {"start": 0, "end": 100})
matches = [
    {"projectId": project.get("projectId"), "organizationId": project.get("organizationId")}
    for project in result.get("projects", [])
    if project.get("name") == "SPY Plus 10 Walk-Forward v2"
]
print({"exact_v2_matches": matches})
PY
```

Expected: 当前组织与已批准 QuantConnect 组织一致；新项目首次创建时 `exact_v2_matches` 为空。若同名 cloud project 已存在但不是本地 config 映射，停止，避免 CLI 自动创建 `SPY Plus 10 Walk-Forward v21`。

- [ ] **只推送精确 v2 项目。**

Working directory: `/home/jingtianyu/projects/spy-plus-10-v2-phase-a/qc-workspace`

Run: `lean cloud push --project "SPY Plus 10 Walk-Forward v2"`

Expected: 输出 `Successfully created cloud project 'SPY Plus 10 Walk-Forward v2'` 或对同一已映射项目的成功更新；不得出现自动改名。

- [ ] **从更新后的 config 读取 `cloud-id`，并确认项目名和 ID。**

Working directory: `/home/jingtianyu/projects/spy-plus-10-v2-phase-a/qc-workspace`

Run: `python -c 'import json; from pathlib import Path; p=Path("SPY Plus 10 Walk-Forward v2/config.json"); d=json.loads(p.read_text()); assert d.get("cloud-id"); print(d["cloud-id"])'`

Expected: 一个正整数 project ID。若 CLI 修改 `config.json`，只提交 ID 映射，不修改算法逻辑；提交消息为 `配置：记录 v2 QuantConnect 项目映射`，并在再次推送 GitHub 前重新验证 private。

- [ ] **用冻结 commit 作为运行参数启动唯一 capability run；先 push 后 backtest，因此 backtest 不带 `--push`。**

Working directory: `/home/jingtianyu/projects/spy-plus-10-v2-phase-a/qc-workspace`

Run:

```bash
V2_CAPABILITY_COMMIT=$(git rev-parse HEAD)
lean cloud backtest "SPY Plus 10 Walk-Forward v2" \
  --name "v2-phase-a-object-store-capability-${V2_CAPABILITY_COMMIT:0:12}" \
  --parameter v2_git_commit "$V2_CAPABILITY_COMMIT" \
  --parameter evidence_run_label phase-a-capability
```

Expected: compile 成功、backtest 进入 terminal state，并输出 project/backtest URL。保存 project ID、compile ID、backtest ID 和 algorithm ID；即使失败也不删除或覆盖该运行。

- [ ] **读取 backtest metadata，确认无 orders/trades 且 runtime statistics 给出所有 keys 和 transport。**

Use read-only API/client calls; expected order count and trade count are zero. Any nonzero count is a Phase A safety failure.

- [ ] **若保存失败，收集明确错误。**

Resolution matrix:

- string PASS + bytes PASS：继续 bytes transport；
- string PASS + bytes FAIL：继续 string fallback，并把 bytes 限制写入报告；
- string FAIL：停止，Phase A=`UNVERIFIED`；检查 Storage Create 权限与 `objectStorageUsed`；
- capacity insufficient：报告所需与现有 bytes，不购买额外 Object Store；
- compile/node/API failure：保留 ID 和错误，Phase A=`UNVERIFIED`，不自动重跑覆盖。

## Task 9: 下载、独立验证并归档 Phase A 证据

**Files:**
- Create: `docs/evidence/v2-phase-a/capability/backtest.json`
- Create: `docs/evidence/v2-phase-a/capability/orders.jsonl`
- Create: `docs/evidence/v2-phase-a/capability/trades.jsonl`
- Create: `docs/evidence/v2-phase-a/capability/object-list.json`
- Create: `docs/evidence/v2-phase-a/capability/key-map.json`
- Create: `docs/evidence/v2-phase-a/capability/fetch-manifest.json`
- Create: `docs/evidence/v2-phase-a/capability/objects/*`
- Create: `docs/evidence/v2-phase-a/capability/verification.json`
- Create: `docs/v2-phase-a-evidence-capability.md`

- [ ] **用本地 credentials 文件执行下载器，不把凭据作为 CLI 参数。**

Run:

```bash
python scripts/fetch_v2_evidence.py \
  --project-id "$V2_PROJECT_ID" \
  --backtest-id "$V2_BACKTEST_ID" \
  --organization-id 02b6527137d1f317d170d3d37c80d59d \
  --output-dir docs/evidence/v2-phase-a/capability
```

Expected: 输出目录原先不存在；下载 1 KB string、1 KB bytes（若平台确实未写成功则由 runtime status 说明）、manifest 和 2015 chunk；不显示 token 或 signed URL。

- [ ] **运行独立 verifier。**

Run:

```bash
python scripts/verify_v2_evidence.py \
  --archive docs/evidence/v2-phase-a/capability \
  --output docs/evidence/v2-phase-a/capability/verification.json
```

Expected: `PASS` 或 `PASS_WITH_STRING_FALLBACK`；任何 `UNVERIFIED` 必须在这里停止，不开始 Phase B。

- [ ] **人工交叉检查 manifest 与 API metadata。**

Run:

```bash
python -m json.tool docs/evidence/v2-phase-a/capability/fetch-manifest.json
python -m json.tool docs/evidence/v2-phase-a/capability/verification.json
python -m unittest tests.test_v2_verifier tests.test_fetch_v2_evidence -v
```

Check: key 唯一；对象 bytes 与下载 bytes 一致；SHA-256 一致；chunk 两日严格递增；四 sleeve PnL 总和为 0；无持仓、订单、交易和 gate failure。

- [ ] **写中文能力报告，只陈述基础设施结论，不宣称策略回报。**

`docs/v2-phase-a-evidence-capability.md` 必须包含：

1. Git commit、组织/project/compile/backtest/algorithm IDs 和 UTC 运行时间；
2. 1 KB string 与 bytes 的云端写后读回、API list/get、长度、SHA-256 结果；
3. Object Store 使用量、权限结果和实际 transport；
4. synthetic chunk/manifest 的 keys、bytes、日期、行数和独立验证状态；
5. sleeve/ablation interface 的人工 fixture 结果；
6. 明确声明没有市场数据、资产订阅、订单、交易、经济绩效或 Phase B 实现；
7. Phase A 最终结论 `PASS`、`PASS_WITH_STRING_FALLBACK` 或 `UNVERIFIED`；
8. 若为 `UNVERIFIED`，列出阻塞点并明确 Phase B 不得开始。

- [ ] **归档前再跑完整验证。**

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q spy_plus_10 scripts "qc-workspace/SPY Plus 10 Walk-Forward v2"
python scripts/verify_v2_foundation.py
git diff --check
git status --short
```

Expected: 全绿；只有报告、允许的证据和可能的 cloud-id 变更未提交。

- [ ] **提交所有成功或失败证据，不删除失败运行。**

Run: `git add docs/evidence/v2-phase-a docs/v2-phase-a-evidence-capability.md "qc-workspace/SPY Plus 10 Walk-Forward v2/config.json" && git commit -m "证据：归档 v2 Phase A 能力验证"`

- [ ] **再次验证 private 后推送并比对远端 hash。**

Run:

```bash
gh repo view Jimmyyu725/spy-plus-10-walk-forward --json visibility,nameWithOwner
git push origin feature/v2-phase-a-evidence
git rev-parse HEAD
git ls-remote origin refs/heads/feature/v2-phase-a-evidence
```

Expected: private；hash 完全一致。

## Task 10: Phase A 关闭门禁与 Phase B 交接

**Files:**
- Read-only review of all Phase A files
- Create Phase B plan only after this task passes and the user approves continuation

- [ ] **按批准规范逐项检查 Phase A 覆盖。**

Checklist:

- 独立 v2 project 存在且 v1 未改；
- string 和 bytes capability 结果均真实保留；
- fallback 只在 string PASS/bytes FAIL 时启用；
- unique keys 包含 project/v2/commit/run/algorithm/year；
- annual chunk <= 5 MB，manifest 含 key/bytes/SHA/date/rows；
- downloader 使用 list/get API，保留 object storage usage；
- independent verifier 不导入 cloud algorithm 的评价逻辑；
- 四 sleeve daily PnL 和四组 removal ablation interface 有人工 fixture；
- 无交易、无 live、无 brokerage、无付费容量购买；
- 任一不完整证据使最终状态为 `UNVERIFIED`。

- [ ] **审查 commit 范围。**

Run:

```bash
git log --oneline main..HEAD
git diff --stat main...HEAD
git diff --name-status main...HEAD
git status --porcelain
```

Expected: worktree clean；v2 Phase A 之外没有实现经济策略或修改 v1 结果。

- [ ] **不要在本计划中合并 main。**

向用户报告 Phase A 结果和 feature branch/commit；只有用户批准 Phase B 后，另写独立的 `v2-phase-b-modules` 实施计划并以实际写计划当天日期命名。若 Phase A 为 `UNVERIFIED`，先修复证据链并产生新、不覆盖的 capability run，不能绕过门禁。

## 最终验证矩阵

| 层级 | 命令/证据 | 通过标准 |
|---|---|---|
| Pure unit | `python -m unittest tests.test_v2_evidence tests.test_v2_attribution tests.test_v2_verifier -v` | 全部通过 |
| Cloud sync | `python scripts/sync_v2_cloud_modules.py` 后 `git diff --exit-code` | canonical 与 cloud copies 字节一致 |
| Foundation | `python scripts/verify_v2_foundation.py` | `V2_FOUNDATION_OK`，无交易/live markers |
| Regression | `python -m unittest discover -s tests -v` | v1 与 v2 全部通过 |
| Compile | `python -m compileall -q spy_plus_10 scripts "qc-workspace/SPY Plus 10 Walk-Forward v2"` 和 QuantConnect compile | 两端均成功 |
| Object Store | cloud read-back + API list/get | string/bytes 或批准的 string fallback 通过 |
| Evidence | manifest/chunk hashes/dates/rows | 独立 verifier PASS |
| Attribution | daily sum + removal paths | Decimal 守恒，四 sleeve 全覆盖 |
| Safety | backtest orders/trades | 均为 0 |
| Git | private check + remote hash | PRIVATE 且远端 hash 等于本地 |

## 实现资料

- [QuantConnect `lean cloud push`](https://www.quantconnect.com/docs/v2/lean-cli/api-reference/lean-cloud-push)：本地未映射项目会创建云端项目；同名未绑定项目可能使 CLI 自动改名，因此 Task 8 必须先检查映射。
- [QuantConnect Object Store algorithm API](https://www.quantconnect.com/docs/v2/writing-algorithms/object-store)：`save`/`read`、`save_bytes`/`read_bytes`、`contains_key`；同键会覆盖，因此本计划强制写前存在检查。
- [QuantConnect Object Store list API](https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/object-store-management/list-object-store-files)：`/object/list` 返回 `objects`、`page`、`totalPages`、`objectStorageUsed`；`/object/get` 可能返回异步 job。
- [QuantConnect Object Store quota](https://www.quantconnect.com/docs/v2/cloud-platform/object-store)：paid organization 有固定免费配额；本计划不授权增加订阅或删除旧对象。
