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
