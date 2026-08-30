#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
import sys
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spy_plus_10.frozen_evaluation import extract_cloud_statistics


BASE_URL = "https://www.quantconnect.com/api/v2"


class QuantConnectApiError(RuntimeError):
    """Raised when a read-only QuantConnect API request fails."""


class _UrllibResponse:
    def __init__(self, response):
        self.content = response.read()
        self.status = getattr(response, "status", 200)

    def raise_for_status(self):
        if not 200 <= self.status < 300:
            raise OSError(f"HTTP status {self.status}")

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class _UrllibSession:
    def post(self, url, *, headers, json: dict, timeout: int):
        payload = __import__("json").dumps(json).encode("utf-8")
        outgoing = request.Request(
            url,
            data=payload,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        return _UrllibResponse(request.urlopen(outgoing, timeout=timeout))

    def get(self, url, *, timeout: int):
        outgoing = request.Request(url, method="GET")
        return _UrllibResponse(request.urlopen(outgoing, timeout=timeout))


def load_credentials(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        user_id = str(payload["user-id"])
        token = str(payload["api-token"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise QuantConnectApiError("QuantConnect credentials are unavailable") from error
    if not user_id or not token:
        raise QuantConnectApiError("QuantConnect credentials are incomplete")
    return user_id, token


class QuantConnectClient:
    def __init__(self, user_id: str, api_token: str, *, session=None):
        self._user_id = str(user_id)
        self._api_token = str(api_token)
        self._session = session or _UrllibSession()

    def _headers(self) -> dict[str, str]:
        timestamp = str(int(time.time()))
        digest = hashlib.sha256(
            f"{self._api_token}:{timestamp}".encode("utf-8")
        ).hexdigest()
        basic = base64.b64encode(
            f"{self._user_id}:{digest}".encode("utf-8")
        ).decode("ascii")
        return {
            "Authorization": f"Basic {basic}",
            "Timestamp": timestamp,
            "User-Agent": "spy-plus-10-evidence-fetcher/1",
        }

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        response = self._session.post(
            f"{BASE_URL}/{endpoint.lstrip('/')}",
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        try:
            response.raise_for_status()
            result = response.json()
        except (OSError, ValueError) as error:
            raise QuantConnectApiError(f"QuantConnect request failed: {endpoint}") from error
        if not isinstance(result, dict) or not result.get("success"):
            errors = result.get("errors", []) if isinstance(result, dict) else []
            raise QuantConnectApiError(
                f"QuantConnect request was rejected: {endpoint}: {errors}"
            )
        return result

    def read_backtest(self, project_id: int, backtest_id: str) -> dict:
        return self._post_json(
            "backtests/read",
            {"projectId": int(project_id), "backtestId": str(backtest_id)},
        )

    def read_all_backtest_rows(
        self,
        endpoint: str,
        field: str,
        project_id: int,
        backtest_id: str,
    ) -> list[dict]:
        rows = []
        start = 0
        page_size = 99
        while True:
            result = self._post_json(
                endpoint,
                {
                    "start": start,
                    "end": start + page_size,
                    "projectId": int(project_id),
                    "backtestId": str(backtest_id),
                },
            )
            page = result.get(field)
            if not isinstance(page, list):
                raise QuantConnectApiError(f"QuantConnect {field} response is invalid")
            rows.extend(page)
            if len(page) < page_size:
                break
            start += len(page)
        return rows

    def download_object(self, organization_id: str, key: str) -> bytes:
        result = self._post_json(
            "object/get",
            {"organizationId": str(organization_id), "keys": [str(key)]},
        )
        job_id = result.get("jobId")
        url = result.get("url")
        for _ in range(30):
            if url:
                break
            if not job_id:
                raise QuantConnectApiError("Object Store download job is missing")
            result = self._post_json(
                "object/get",
                {"organizationId": str(organization_id), "jobId": str(job_id)},
            )
            url = result.get("url")
            if not url:
                time.sleep(1)
        if not url:
            raise QuantConnectApiError("Object Store download did not become ready")
        response = self._session.get(str(url), timeout=60)
        try:
            response.raise_for_status()
        except OSError as error:
            raise QuantConnectApiError("Object Store file download failed") from error
        content = response.content
        if content.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                if len(files) != 1:
                    raise QuantConnectApiError("Object Store archive is ambiguous")
                content = archive.read(files[0])
        return content


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def fetch_evidence(
    client: QuantConnectClient,
    *,
    project_id: int,
    backtest_id: str,
    organization_id: str,
    output_dir: Path,
) -> dict:
    if output_dir.exists():
        raise QuantConnectApiError(f"output directory already exists: {output_dir}")
    backtest = client.read_backtest(project_id, backtest_id)
    statistics = extract_cloud_statistics(backtest)
    evidence_key = statistics.get("FORMAL_EVIDENCE_KEY")
    if not evidence_key:
        raise QuantConnectApiError("formal evidence key is missing from backtest")
    orders = client.read_all_backtest_rows(
        "backtests/orders/read", "orders", project_id, backtest_id
    )
    trades = client.read_all_backtest_rows(
        "backtests/trades/read", "trades", project_id, backtest_id
    )
    evidence_bytes = client.download_object(organization_id, evidence_key)
    try:
        evidence = json.loads(gzip.decompress(evidence_bytes).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QuantConnectApiError("formal evidence artifact is not valid gzip JSON") from error
    output_dir.mkdir(parents=True)
    (output_dir / "backtest.json").write_text(
        json.dumps(backtest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "orders.jsonl", orders)
    _write_jsonl(output_dir / "trades.jsonl", trades)
    (output_dir / "daily-evidence.json.gz").write_bytes(evidence_bytes)
    (output_dir / "daily-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "project_id": int(project_id),
        "backtest_id": str(backtest_id),
        "organization_id": str(organization_id),
        "evidence_key": evidence_key,
        "order_count": len(orders),
        "trade_count": len(trades),
        "daily_count": len(evidence.get("daily", [])),
        "audit_sample_count": len(evidence.get("audit_samples", [])),
    }
    (output_dir / "fetch-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch frozen QuantConnect evidence")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--backtest-id", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path.home() / ".lean" / "credentials",
    )
    arguments = parser.parse_args()
    user_id, token = load_credentials(arguments.credentials)
    client = QuantConnectClient(user_id, token)
    manifest = fetch_evidence(
        client,
        project_id=arguments.project_id,
        backtest_id=arguments.backtest_id,
        organization_id=arguments.organization_id,
        output_dir=arguments.output_dir,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
