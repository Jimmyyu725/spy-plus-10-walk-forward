import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from spy_plus_10.frozen_evaluation import verify_frozen_evidence


def evidence_fixture():
    daily = [
        {
            "date": "2015-01-02",
            "strategy_equity": "1000000",
            "spy_equity": "1000000",
            "drawdown": "0",
        }
    ]
    strategy = Decimal("1000000")
    spy = Decimal("1000000")
    for year in range(2015, 2027):
        strategy *= Decimal("1.20")
        spy *= Decimal("1.05")
        day = date(year, 8, 28) if year == 2026 else date(year, 12, 31)
        daily.append(
            {
                "date": day.isoformat(),
                "strategy_equity": str(strategy),
                "spy_equity": str(spy),
                "drawdown": "0",
            }
        )
    samples = []
    origin = datetime(2015, 1, 2, tzinfo=timezone.utc)
    for sequence in range(10):
        cutoff = origin + timedelta(days=sequence * 7)
        samples.append(
            {
                "sequence": sequence + 1,
                "module": "FUTURES",
                "data_cutoff": cutoff.isoformat(),
                "signal_time": (cutoff + timedelta(hours=1)).isoformat(),
                "order_time": (cutoff + timedelta(days=1)).isoformat(),
                "fill_time": (cutoff + timedelta(days=2)).isoformat(),
            }
        )
    return {
        "schema_version": 1,
        "run": {
            "project_id": 35858890,
            "algorithm_id": "abc123",
            "run_label": "base",
            "slippage_multiplier": 1.0,
            "evaluation_mode": "frozen-evaluation",
            "start_date": "2012-01-01",
            "trading_start_date": "2015-01-02",
            "end_date": "2026-08-28",
            "timezone": "America/New_York",
        },
        "daily": daily,
        "audit_samples": samples,
        "gate_failures": [],
        "licenses": {"equity": "AVAILABLE", "option": "AVAILABLE"},
    }


def cloud_statistics(payload):
    strategy_prior = spy_prior = Decimal("1000000")
    by_year = {}
    for row in payload["daily"]:
        by_year[date.fromisoformat(row["date"]).year] = row
    statistics = {
        "PORTFOLIO_MAX_DRAWDOWN": "0",
        "FORMAL_DATA_AUDIT_STATUS": "PASS",
        "FORMAL_SAFETY_GATE_STATUS": "PASS",
        "FORMAL_EVIDENCE_SAVE_STATUS": "PASS",
    }
    for year in range(2015, 2027):
        row = by_year[year]
        strategy = Decimal(row["strategy_equity"])
        spy = Decimal(row["spy_equity"])
        strategy_return = strategy / strategy_prior - 1
        spy_return = spy / spy_prior - 1
        status = "PASS" if strategy_return >= spy_return + Decimal("0.10") else "FAIL"
        period = "PARTIAL_YEAR" if year == 2026 else "FULL_YEAR"
        statistics[f"FORMAL_YEAR_{year}"] = (
            f"{period},strategy={strategy_return},spy={spy_return},"
            f"excess={strategy_return - spy_return},status={status}"
        )
        strategy_prior, spy_prior = strategy, spy
    statistics["FORMAL_ANNUAL_GATE_STATUS"] = (
        "PASS"
        if all("status=PASS" in value for key, value in statistics.items() if key.startswith("FORMAL_YEAR_"))
        else "FAIL"
    )
    statistics["FORMAL_OVERALL_STATUS"] = statistics["FORMAL_ANNUAL_GATE_STATUS"]
    return statistics


class FrozenEvaluationVerifierTests(unittest.TestCase):
    def test_passing_evidence_recomputes_every_year_and_drawdown(self):
        payload = evidence_fixture()
        result = verify_frozen_evidence(payload, cloud_statistics(payload))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["annual_rows"]), 12)
        self.assertEqual(result["annual_rows"][-1]["period"], "PARTIAL_YEAR")
        self.assertEqual(result["maximum_drawdown"], "0")

    def test_verified_annual_miss_is_fail(self):
        payload = evidence_fixture()
        row = next(row for row in payload["daily"] if row["date"] == "2018-12-31")
        previous = next(row for row in payload["daily"] if row["date"] == "2017-12-31")
        row["strategy_equity"] = str(Decimal(previous["strategy_equity"]) * Decimal("1.10"))
        result = verify_frozen_evidence(payload, cloud_statistics(payload))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(2018, result["failed_years"])

    def test_missing_or_noncausal_audit_is_unverified(self):
        missing = evidence_fixture()
        missing["audit_samples"] = missing["audit_samples"][:9]
        self.assertEqual(
            verify_frozen_evidence(missing, cloud_statistics(missing))["status"],
            "UNVERIFIED",
        )
        noncausal = evidence_fixture()
        noncausal["audit_samples"][0]["fill_time"] = noncausal["audit_samples"][0]["order_time"]
        self.assertEqual(
            verify_frozen_evidence(noncausal, cloud_statistics(noncausal))["status"],
            "UNVERIFIED",
        )

    def test_reconciliation_tolerance_is_at_most_one_basis_point_of_return(self):
        payload = evidence_fixture()
        within = cloud_statistics(payload)
        within["FORMAL_YEAR_2015"] = within["FORMAL_YEAR_2015"].replace(
            "strategy=0.20", "strategy=0.2001"
        )
        self.assertEqual(verify_frozen_evidence(payload, within)["status"], "PASS")
        outside = cloud_statistics(payload)
        outside["FORMAL_YEAR_2015"] = outside["FORMAL_YEAR_2015"].replace(
            "strategy=0.20", "strategy=0.2001001"
        )
        self.assertEqual(
            verify_frozen_evidence(payload, outside)["status"],
            "UNVERIFIED",
        )


if __name__ == "__main__":
    unittest.main()
