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
