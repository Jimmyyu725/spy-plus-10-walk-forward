import unittest

from spy_plus_10.audit_baseline_record import render_audit_baseline_record


class AuditBaselineRecordTests(unittest.TestCase):
    def test_record_is_non_formal_and_identifies_cloud_run(self):
        text = render_audit_baseline_record(
            lean_version="lean 1.0.229",
            git_commit="a" * 40,
            project_id="123456",
            backtest_id="abc-def",
            result_url="https://www.quantconnect.com/project/123456/abc-def",
            test_count=36,
        )
        self.assertIn("Formal evaluation: false", text)
        self.assertIn("Local fixture tests: 36 passed", text)
        self.assertIn("QuantConnect backtest ID: abc-def", text)


if __name__ == "__main__":
    unittest.main()
