# Cloud Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Atlas 上建立可审计的 LEAN CLI 控制面，连接正确的 QuantConnect 付费组织，创建 `SPY Plus 10 Walk-Forward` 云端项目，并通过一个明确标记为非正式评价的最小云端回测。

**Architecture:** Git 仓库根目录保存规范、验证器和测试；`qc-workspace/` 是 QuantConnect organization workspace；`qc-workspace/SPY Plus 10 Walk-Forward/` 是同步到 QuantConnect Cloud 的 Python 项目。Atlas 不下载完整历史行情、不运行本地 LEAN Docker 回测；所有 LEAN 编译和行情回测在 QuantConnect Cloud 执行。

**Tech Stack:** Ubuntu 24.04, Python 3.12 standard library, `unittest`, pipx, LEAN CLI, QuantConnect Cloud, Git, GitHub CLI.

---

## Scope and file map

本计划只实施总规范的第一个里程碑 `Cloud Foundation`。以下模块分别需要后续独立计划：Audit Baseline、Futures Trend、Equity Factor、Defined-Risk Option、Portfolio Integration 和 Frozen Evaluation。

本里程碑创建或修改：

- Modify: `.gitignore` — 忽略 LEAN 本地样例数据、Object Store、编辑器状态和生成结果。
- Create: `qc-workspace/lean.json` — 由 `lean init` 生成的 organization workspace 配置；提交前验证不含 API Token。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/main.py` — 仅用于验证云端编译和数据访问的 SPY smoke algorithm。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/config.json` — 由 `lean project-create` 生成的项目配置。
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/project-manifest.json` — 明确标记 smoke run 不是正式策略评价。
- Create: `spy_plus_10/__init__.py` — 本地审计包入口。
- Create: `spy_plus_10/foundation.py` — 验证 workspace、smoke project、安全边界和凭据泄漏。
- Create: `spy_plus_10/foundation_record.py` — 从 QuantConnect 结果 URL 提取云端 ID 并生成证据文档。
- Create: `scripts/verify_cloud_foundation.py` — 命令行验证入口。
- Create: `scripts/write_cloud_foundation_record.py` — 使用实际运行值生成云端证据文档。
- Create: `tests/test_foundation.py` — 使用人工临时目录测试验证器，不读取市场数据。
- Create: `tests/test_foundation_record.py` — 使用人工 URL 测试证据解析和生成。
- Create: `docs/cloud-foundation.md` — 记录实际 CLI 版本、组织、云端项目与 smoke backtest 证据。

权威设计：[2026-08-30-spy-plus-10-walk-forward-design.md](../specs/2026-08-30-spy-plus-10-walk-forward-design.md)。

### Task 1: Install and authenticate LEAN CLI

**Files:**
- Inspect: `/home/jingtianyu/.lean/credentials`
- No repository files changed

- [ ] **Step 1: Reconfirm host prerequisites**

Run:

```bash
python3 --version
pipx --version
docker --version
git --version
df -h /home/jingtianyu
```

Expected: Python 3.12, working pipx, Docker installed, Git installed, and more than 60 GiB free. Docker is recorded only as an available fallback; this plan must not run `lean backtest`, `lean research`, or pull a LEAN Docker image.

- [ ] **Step 2: Verify LEAN CLI is initially absent or identify its installed version**

Run:

```bash
if command -v lean >/dev/null 2>&1; then lean --version; else echo "lean:not-installed"; fi
```

Expected before first execution: `lean:not-installed`. If LEAN is already installed, record its version and use `pipx upgrade lean` instead of installing a second copy.

- [ ] **Step 3: Install LEAN CLI in an isolated pipx environment**

Run when absent:

```bash
pipx install lean
```

Run when already present under pipx:

```bash
pipx upgrade lean
```

Expected: pipx reports package `lean` installed or upgraded successfully. Do not use `sudo pip`, system Python package mutation, or a project virtual environment for the CLI.

- [ ] **Step 4: Verify the executable and package owner**

Run:

```bash
command -v lean
lean --version
pipx list --short
```

Expected: `lean` resolves under `/home/jingtianyu/.local/bin/`, prints a version, and appears exactly once in the pipx list.

- [ ] **Step 5: Authenticate without echoing or logging the API Token**

Run `lean login` in a PTY. Supply the already obtained User ID and API Token only to the CLI prompts. Do not pass the token as a command-line option, environment variable printed by `env`, shell history entry, repository file, or transcript output.

```bash
lean login
```

Expected: `Successfully logged in`. If QuantConnect requests MFA, CAPTCHA, or a new browser confirmation, stop and ask the user to complete only that challenge.

- [ ] **Step 6: Restrict credentials and verify the paid account**

Run:

```bash
chmod 600 /home/jingtianyu/.lean/credentials
stat -c '%a %n' /home/jingtianyu/.lean/credentials
lean whoami
```

Expected: mode `600`; `lean whoami` identifies the intended account and at least one paid organization. Do not print the credential file.

### Task 2: Initialize the organization workspace

**Files:**
- Modify: `.gitignore`
- Create: `qc-workspace/lean.json`
- Generated and ignored: `qc-workspace/data/`
- Generated and ignored: `qc-workspace/storage/`

- [ ] **Step 1: Extend ignore rules before running the generator**

Apply this patch:

```diff
 .DS_Store
+qc-workspace/data/
+qc-workspace/storage/
+qc-workspace/**/.idea/
+qc-workspace/**/.vscode/
+qc-workspace/**/backtests/
+qc-workspace/**/research/
+qc-workspace/**/research.ipynb
```

- [ ] **Step 2: Verify the intended workspace directory is absent or empty**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
if [ -d "$project_root/qc-workspace" ]; then find "$project_root/qc-workspace" -mindepth 1 -maxdepth 1 -print; else echo "qc-workspace:absent"; fi
```

Expected: `qc-workspace:absent` or no listed entries. If files exist, stop and inspect them; do not overwrite an existing workspace.

- [ ] **Step 3: Create and link the empty workspace to the paid organization**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
mkdir -p "$project_root/qc-workspace"
cd "$project_root/qc-workspace"
lean init --language python --organization 02b6527137d1f317d170d3d37c80d59d
```

Expected: `lean init` creates `lean.json`, `data/`, and `storage/` for the selected organization without starting Docker.

- [ ] **Step 4: Validate generated boundaries before staging**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
test -f "$project_root/qc-workspace/lean.json"
test -d "$project_root/qc-workspace/data"
test -d "$project_root/qc-workspace/storage"
git -C "$project_root" check-ignore qc-workspace/data qc-workspace/storage
if rg -n --hidden --glob '!.git/**' '[a-f0-9]{64}' "$project_root/qc-workspace/lean.json"; then exit 1; else echo "lean-json-secret-scan:clean"; fi
```

Expected: both generated directories are ignored and `lean-json-secret-scan:clean` is printed. A 64-character hexadecimal value in `lean.json` is treated as possible credential material and blocks staging until understood.

- [ ] **Step 5: Commit the workspace configuration**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
git -C "$project_root" add .gitignore qc-workspace/lean.json
git -C "$project_root" diff --cached --check
git -C "$project_root" diff --cached --stat
git -C "$project_root" commit -m "build: initialize QuantConnect cloud workspace"
```

Expected: one commit containing only `.gitignore` and `qc-workspace/lean.json`; generated data and storage remain untracked and ignored.

### Task 3: Build the foundation validator with TDD

**Files:**
- Create: `spy_plus_10/__init__.py`
- Create: `spy_plus_10/foundation.py`
- Create: `spy_plus_10/foundation_record.py`
- Create: `scripts/verify_cloud_foundation.py`
- Create: `scripts/write_cloud_foundation_record.py`
- Create: `tests/test_foundation.py`
- Create: `tests/test_foundation_record.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/test_foundation.py` with:

```python
import json
import tempfile
import unittest
from pathlib import Path

from spy_plus_10.foundation import FoundationValidationError, validate_foundation


VALID_MAIN = """from AlgorithmImports import *

class SpyPlusTenWalkForward(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 9)
        self.set_cash(1_000_000)
        self.spy = self.add_equity(\"SPY\", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)
"""


class FoundationValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_valid_tree(self):
        workspace = self.root / "qc-workspace"
        project = workspace / "SPY Plus 10 Walk-Forward"
        project.mkdir(parents=True)
        (workspace / "lean.json").write_text("{}\n", encoding="utf-8")
        (project / "config.json").write_text("{}\n", encoding="utf-8")
        (project / "main.py").write_text(VALID_MAIN, encoding="utf-8")
        manifest = {
            "benchmark": "SPY",
            "end_date": "2015-01-09",
            "formal_evaluation": False,
            "initial_cash": 1_000_000,
            "language": "Python",
            "live_trading": False,
            "mode": "foundation-smoke",
            "name": "SPY Plus 10 Walk-Forward",
            "start_date": "2015-01-02",
        }
        (project / "project-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_missing_workspace_fails_closed(self):
        with self.assertRaisesRegex(FoundationValidationError, "lean.json"):
            validate_foundation(self.root)

    def test_valid_foundation_passes(self):
        self.create_valid_tree()
        result = validate_foundation(self.root)
        self.assertEqual(result.project_name, "SPY Plus 10 Walk-Forward")
        self.assertEqual(result.mode, "foundation-smoke")
        self.assertFalse(result.formal_evaluation)

    def test_plaintext_token_pattern_fails(self):
        self.create_valid_tree()
        leaked = "a" * 64
        (self.root / "leak.txt").write_text(leaked, encoding="utf-8")
        with self.assertRaisesRegex(FoundationValidationError, "credential-like"):
            validate_foundation(self.root)

    def test_live_trading_marker_fails(self):
        self.create_valid_tree()
        project = self.root / "qc-workspace" / "SPY Plus 10 Walk-Forward"
        manifest = json.loads((project / "project-manifest.json").read_text())
        manifest["live_trading"] = True
        (project / "project-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(FoundationValidationError, "live_trading"):
            validate_foundation(self.root)


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_foundation_record.py` with:

```python
import unittest

from spy_plus_10.foundation_record import parse_result_url, render_foundation_record


class FoundationRecordTests(unittest.TestCase):
    def test_parse_result_url_with_backtest_segment(self):
        project_id, backtest_id = parse_result_url(
            "https://www.quantconnect.com/project/12345678/backtest/abc-def"
        )
        self.assertEqual(project_id, "12345678")
        self.assertEqual(backtest_id, "abc-def")

    def test_parse_result_url_without_backtest_segment(self):
        project_id, backtest_id = parse_result_url(
            "https://www.quantconnect.com/project/12345678/abc-def"
        )
        self.assertEqual(project_id, "12345678")
        self.assertEqual(backtest_id, "abc-def")

    def test_reject_non_quantconnect_url(self):
        with self.assertRaisesRegex(ValueError, "QuantConnect HTTPS"):
            parse_result_url("https://example.com/project/123/backtest/abc")

    def test_render_record_contains_runtime_evidence(self):
        text = render_foundation_record(
            lean_version="lean 1.2.3",
            git_commit="a" * 40,
            organization_id="org-123",
            result_url="https://www.quantconnect.com/project/12345678/backtest/abc-def",
        )
        self.assertIn("Formal evaluation: false", text)
        self.assertIn("QuantConnect project ID: 12345678", text)
        self.assertIn("QuantConnect backtest ID: abc-def", text)
        self.assertIn("Git commit: " + "a" * 40, text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```bash
cd /home/jingtianyu/projects/spy-plus-10-walk-forward
python3 -m unittest tests/test_foundation.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'spy_plus_10'`.

- [ ] **Step 3: Implement the minimal validator**

Create `spy_plus_10/__init__.py` with:

```python
"""Local audit helpers for the SPY Plus 10 project."""
```

Create `spy_plus_10/foundation.py` with:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_NAME = "SPY Plus 10 Walk-Forward"
TOKEN_PATTERN = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.IGNORECASE)
TEXT_SUFFIXES = {".json", ".md", ".py", ".sh", ".toml", ".txt", ".yml", ".yaml"}


class FoundationValidationError(RuntimeError):
    """Raised when the cloud foundation is incomplete or unsafe."""


@dataclass(frozen=True)
class FoundationStatus:
    project_name: str
    mode: str
    formal_evaluation: bool


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FoundationValidationError(f"missing required file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundationValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FoundationValidationError(f"expected JSON object: {path}")
    return value


def _scan_for_credentials(root: Path) -> None:
    excluded_parts = {".git", "__pycache__", "data", "storage"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if TOKEN_PATTERN.search(text):
            raise FoundationValidationError(f"credential-like token found: {path}")


def validate_foundation(root: Path) -> FoundationStatus:
    root = root.resolve()
    workspace = root / "qc-workspace"
    project = workspace / PROJECT_NAME
    _read_json(workspace / "lean.json")
    _read_json(project / "config.json")
    manifest = _read_json(project / "project-manifest.json")
    main_path = project / "main.py"
    if not main_path.is_file():
        raise FoundationValidationError("missing required file: main.py")
    main_source = main_path.read_text(encoding="utf-8")

    expected_manifest = {
        "benchmark": "SPY",
        "end_date": "2015-01-09",
        "formal_evaluation": False,
        "initial_cash": 1_000_000,
        "language": "Python",
        "live_trading": False,
        "mode": "foundation-smoke",
        "name": PROJECT_NAME,
        "start_date": "2015-01-02",
    }
    if manifest != expected_manifest:
        differing = sorted(set(manifest.items()) ^ set(expected_manifest.items()))
        raise FoundationValidationError(f"project manifest mismatch: {differing}")
    if manifest["live_trading"]:
        raise FoundationValidationError("live_trading must remain false")

    required_markers = (
        "class SpyPlusTenWalkForward(QCAlgorithm)",
        "self.set_start_date(2015, 1, 2)",
        "self.set_end_date(2015, 1, 9)",
        "self.set_cash(1_000_000)",
        'self.add_equity("SPY", Resolution.DAILY)',
        "self.set_benchmark(self.spy)",
    )
    missing = [marker for marker in required_markers if marker not in main_source]
    if missing:
        raise FoundationValidationError(f"main.py missing markers: {missing}")
    forbidden_markers = ("set_brokerage_model", "set_live_mode", "add_option", "add_future")
    present = [marker for marker in forbidden_markers if marker in main_source]
    if present:
        raise FoundationValidationError(f"foundation smoke contains forbidden markers: {present}")

    _scan_for_credentials(root)
    return FoundationStatus(
        project_name=manifest["name"],
        mode=manifest["mode"],
        formal_evaluation=manifest["formal_evaluation"],
    )
```

Create `scripts/verify_cloud_foundation.py` with:

```python
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
```

Create `spy_plus_10/foundation_record.py` with:

```python
from __future__ import annotations

import re
from urllib.parse import urlparse


ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def parse_result_url(result_url: str) -> tuple[str, str]:
    parsed = urlparse(result_url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "quantconnect.com",
        "www.quantconnect.com",
    }:
        raise ValueError("expected QuantConnect HTTPS result URL")
    parts = [part for part in parsed.path.split("/") if part]
    try:
        project_index = parts.index("project")
        project_id = parts[project_index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("result URL is missing project ID") from exc
    if "backtest" in parts[project_index + 2 :]:
        backtest_index = parts.index("backtest", project_index + 2)
        try:
            backtest_id = parts[backtest_index + 1]
        except IndexError as exc:
            raise ValueError("result URL is missing backtest ID") from exc
    elif len(parts) > project_index + 2:
        backtest_id = parts[-1]
    else:
        raise ValueError("result URL is missing backtest ID")
    if not ID_PATTERN.fullmatch(project_id) or not ID_PATTERN.fullmatch(backtest_id):
        raise ValueError("result URL contains invalid project or backtest ID")
    return project_id, backtest_id


def render_foundation_record(
    *,
    lean_version: str,
    git_commit: str,
    organization_id: str,
    result_url: str,
) -> str:
    project_id, backtest_id = parse_result_url(result_url)
    if not re.fullmatch(r"[0-9a-f]{40}", git_commit):
        raise ValueError("expected a full Git commit hash")
    return f"""# QuantConnect Cloud Foundation

- Purpose: connectivity and compilation smoke test only
- Formal evaluation: false
- Project: SPY Plus 10 Walk-Forward
- Organization ID: {organization_id}
- Initial cash: 1,000,000 USD
- Backtest range: 2015-01-02 through 2015-01-09
- Benchmark: SPY
- Live trading: disabled
- LEAN CLI version: {lean_version.strip()}
- Git commit: {git_commit}
- QuantConnect project ID: {project_id}
- QuantConnect backtest ID: {backtest_id}
- Result URL: {result_url}
- Cloud status: completed
"""
```

Create `scripts/write_cloud_foundation_record.py` with:

```python
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
```

- [ ] **Step 4: Run the isolated unit tests**

Run:

```bash
cd /home/jingtianyu/projects/spy-plus-10-walk-forward
python3 -m unittest tests/test_foundation.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit the validator**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
git -C "$project_root" add spy_plus_10/__init__.py spy_plus_10/foundation.py spy_plus_10/foundation_record.py scripts/verify_cloud_foundation.py scripts/write_cloud_foundation_record.py tests/test_foundation.py tests/test_foundation_record.py
git -C "$project_root" diff --cached --check
git -C "$project_root" commit -m "test: add cloud foundation safety validator"
```

Expected: one commit containing the validator, evidence generator, and eight unit tests.

### Task 4: Create the non-formal cloud smoke project with TDD

**Files:**
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/main.py`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/config.json`
- Create: `qc-workspace/SPY Plus 10 Walk-Forward/project-manifest.json`
- Modify: `tests/test_foundation.py`

- [ ] **Step 1: Add a repository-level failing contract test**

Add this method to `FoundationValidationTests` in `tests/test_foundation.py`:

```python
    def test_repository_foundation_contract(self):
        repository_root = Path(__file__).resolve().parents[1]
        status = validate_foundation(repository_root)
        self.assertEqual(status.project_name, "SPY Plus 10 Walk-Forward")
        self.assertEqual(status.mode, "foundation-smoke")
        self.assertFalse(status.formal_evaluation)
```

- [ ] **Step 2: Run the new test and verify it fails before project creation**

Run:

```bash
cd /home/jingtianyu/projects/spy-plus-10-walk-forward
python3 -m unittest tests.test_foundation.FoundationValidationTests.test_repository_foundation_contract -v
```

Expected: FAIL because `qc-workspace/SPY Plus 10 Walk-Forward/config.json` does not exist.

- [ ] **Step 3: Check for an existing cloud project before creating a local project**

From `qc-workspace/`, run:

```bash
cd "/home/jingtianyu/projects/spy-plus-10-walk-forward/qc-workspace"
lean cloud pull --project "SPY Plus 10 Walk-Forward"
```

Expected for a new account: a clear “project not found” error and no new project directory. If the pull succeeds, stop and inspect the pulled files and project identity before changing them; do not create a duplicate or push over unknown cloud content.

- [ ] **Step 4: Generate the local Python project**

Only after Step 3 confirms no existing project, run:

```bash
cd "/home/jingtianyu/projects/spy-plus-10-walk-forward/qc-workspace"
lean project-create "SPY Plus 10 Walk-Forward" --language python
```

Expected: LEAN creates the named directory with `main.py`, `config.json`, `research.ipynb`, and ignored editor metadata.

- [ ] **Step 5: Replace starter code with the bounded smoke algorithm**

Replace `qc-workspace/SPY Plus 10 Walk-Forward/main.py` with:

```python
from AlgorithmImports import *


class SpyPlusTenWalkForward(QCAlgorithm):
    """Cloud-only connectivity smoke test; not a formal strategy evaluation."""

    def initialize(self):
        self.set_start_date(2015, 1, 2)
        self.set_end_date(2015, 1, 9)
        self.set_cash(1_000_000)
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

    def on_data(self, data: Slice):
        if not self.portfolio.invested and data.bars.contains_key(self.spy):
            self.set_holdings(self.spy, 1.0)
```

Create `qc-workspace/SPY Plus 10 Walk-Forward/project-manifest.json` with:

```json
{
  "benchmark": "SPY",
  "end_date": "2015-01-09",
  "formal_evaluation": false,
  "initial_cash": 1000000,
  "language": "Python",
  "live_trading": false,
  "mode": "foundation-smoke",
  "name": "SPY Plus 10 Walk-Forward",
  "start_date": "2015-01-02"
}
```

- [ ] **Step 6: Run the contract test and the full local foundation suite**

Run:

```bash
cd /home/jingtianyu/projects/spy-plus-10-walk-forward
python3 -m unittest tests.test_foundation.FoundationValidationTests.test_repository_foundation_contract -v
python3 -m unittest discover -s tests -v
python3 scripts/verify_cloud_foundation.py
```

Expected: repository contract PASS, all 9 tests PASS, and:

```text
foundation:PASS:project=SPY Plus 10 Walk-Forward:mode=foundation-smoke:formal_evaluation=false
```

- [ ] **Step 7: Commit the bounded smoke project**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
git -C "$project_root" add "qc-workspace/SPY Plus 10 Walk-Forward/main.py" "qc-workspace/SPY Plus 10 Walk-Forward/config.json" "qc-workspace/SPY Plus 10 Walk-Forward/project-manifest.json" tests/test_foundation.py
git -C "$project_root" diff --cached --check
git -C "$project_root" commit -m "feat: add bounded QuantConnect cloud smoke project"
```

Expected: generated notebook and editor state remain unstaged; the committed project cannot enable live trading or run the formal 2015–latest evaluation.

### Task 5: Push, compile, and run the cloud smoke backtest

**Files:**
- Create after successful cloud run: `docs/cloud-foundation.md`

- [ ] **Step 1: Re-run safety validation immediately before cloud synchronization**

Run:

```bash
cd /home/jingtianyu/projects/spy-plus-10-walk-forward
python3 -m unittest discover -s tests -v
python3 scripts/verify_cloud_foundation.py
git status --short --branch
```

Expected: all tests PASS, validator PASS, and only intentional ignored generator outputs exist.

- [ ] **Step 2: Push only the named project without force**

Run:

```bash
cd "/home/jingtianyu/projects/spy-plus-10-walk-forward/qc-workspace"
lean cloud push --project "SPY Plus 10 Walk-Forward"
```

Expected: output names exactly `SPY Plus 10 Walk-Forward` and says the cloud project/file was created or updated. If LEAN appends `1`, reports a lock conflict, or names a different organization, stop; do not use `--force` and do not continue to backtest.

- [ ] **Step 3: Run the bounded cloud backtest and generate the evidence file**

Run:

```bash
cd "/home/jingtianyu/projects/spy-plus-10-walk-forward/qc-workspace"
smoke_commit=$(git -C .. rev-parse --short HEAD)
smoke_commit_full=$(git -C .. rev-parse HEAD)
smoke_log=$(mktemp)
lean cloud backtest "SPY Plus 10 Walk-Forward" --push --name "foundation-smoke-${smoke_commit}" | tee "$smoke_log"
backtest_url=$(rg -o 'https://www\.quantconnect\.com/[^[:space:]]+' "$smoke_log" | tail -n 1 | sed 's/[),.;]*$//')
test -n "$backtest_url"
python3 ../scripts/write_cloud_foundation_record.py \
  --lean-version "$(lean --version | head -n 1)" \
  --git-commit "$smoke_commit_full" \
  --organization-id "02b6527137d1f317d170d3d37c80d59d" \
  --result-url "$backtest_url" \
  --output ../docs/cloud-foundation.md
rm -f "$smoke_log"
```

Expected: cloud compilation succeeds, the backtest covers only `2015-01-02` through `2015-01-09`, the CLI prints a QuantConnect result URL, and the generator writes `docs/cloud-foundation.md`. This run must never be presented as evidence for the SPY+10 objective.

- [ ] **Step 4: Inspect cloud evidence and write the foundation record**

Open the generated result URL read-only and verify: project name, backtest name, date range, starting cash, SPY subscription, completed status, and absence of live deployment. Compare the displayed project and backtest IDs with `docs/cloud-foundation.md`. If any value differs, stop and diagnose the parser or selected URL before staging.

- [ ] **Step 5: Verify and commit cloud evidence**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
if rg -n '[a-f0-9]{64}' "$project_root/docs/cloud-foundation.md"; then exit 1; fi
python3 "$project_root/scripts/verify_cloud_foundation.py"
git -C "$project_root" add docs/cloud-foundation.md
git -C "$project_root" diff --cached --check
git -C "$project_root" commit -m "docs: record verified QuantConnect cloud foundation"
```

Expected: one evidence commit with exact cloud IDs and no credentials.

### Task 6: Final verification and private backup

**Files:**
- Verify all files from Tasks 1–5
- No new files expected

- [ ] **Step 1: Run the complete milestone verification**

Run:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
cd "$project_root"
python3 -m unittest discover -s tests -v
python3 scripts/verify_cloud_foundation.py
git diff --check
git status --short --branch
lean whoami
```

Expected: 9 tests PASS; foundation validator PASS; no tracked worktree changes; authenticated paid organization shown.

- [ ] **Step 2: Verify the exact GitHub destination remains private**

Run:

```bash
git -C /home/jingtianyu/projects/spy-plus-10-walk-forward remote get-url origin
gh repo view Jimmyyu725/spy-plus-10-walk-forward --json visibility,nameWithOwner,url
```

Expected: remote resolves to `Jimmyyu725/spy-plus-10-walk-forward` and visibility is exactly `PRIVATE`. Any other visibility blocks the push.

- [ ] **Step 3: Push main and prove remote synchronization**

Run only after Step 2 passes:

```bash
project_root=/home/jingtianyu/projects/spy-plus-10-walk-forward
git -C "$project_root" push origin main
local_commit=$(git -C "$project_root" rev-parse HEAD)
remote_commit=$(git -C "$project_root" ls-remote origin refs/heads/main | awk '{print $1}')
test "$local_commit" = "$remote_commit"
echo "remote-sync:verified"
```

Expected: push succeeds and `remote-sync:verified` prints.

- [ ] **Step 4: Milestone completion gate**

Confirm all statements are true before starting the Audit Baseline plan:

```text
LEAN CLI is installed once under pipx.
LEAN CLI authenticates to the intended paid organization.
Credentials exist only in the user-level LEAN credential store with mode 600.
The Git repository contains an organization workspace but no downloaded market history.
The cloud project name is exactly SPY Plus 10 Walk-Forward.
The bounded smoke backtest compiled and completed in QuantConnect Cloud.
The smoke run is marked formal_evaluation=false and cannot be mistaken for a strategy result.
No live brokerage, live node, paper account, or real order was configured.
All tests and the foundation validator pass.
The final commit is synchronized to a GitHub repository verified PRIVATE.
```

If any statement is false or unsupported, the milestone remains incomplete and the next plan must not begin.
