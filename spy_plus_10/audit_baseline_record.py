from __future__ import annotations

import re


ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def render_audit_baseline_record(
    *,
    lean_version: str,
    git_commit: str,
    project_id: str,
    backtest_id: str,
    result_url: str,
    test_count: int,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", git_commit):
        raise ValueError("expected a full Git commit hash")
    if not ID_PATTERN.fullmatch(project_id) or not ID_PATTERN.fullmatch(backtest_id):
        raise ValueError("invalid cloud identifier")
    expected_url = f"https://www.quantconnect.com/project/{project_id}/{backtest_id}"
    if result_url != expected_url:
        raise ValueError("result URL does not match cloud identifiers")
    if test_count <= 0:
        raise ValueError("test_count must be positive")
    return f"""# QuantConnect Audit Baseline

- Purpose: baseline module compilation and bounded smoke test only
- Formal evaluation: false
- Live trading: disabled
- Initial cash: 1,000,000 USD
- Smoke range: 2015-01-02 through 2015-01-09
- LEAN CLI version: {lean_version.strip()}
- Git commit: {git_commit}
- Local fixture tests: {test_count} passed
- QuantConnect project ID: {project_id}
- QuantConnect backtest ID: {backtest_id}
- Result URL: {result_url}
- Cloud status: completed
"""
