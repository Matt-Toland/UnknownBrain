"""
Tests for src.cost_logger.

Covers:
  - Cost lookup: exact match + prefix match for variants + None for unknown
  - Cost estimate maths
  - Token extraction handles both OpenAI API shapes
  - log_llm_call disabled by SCORING_COST_LOG_DISABLED
  - log_llm_call writes a properly-shaped row to BigQuery
  - log_llm_call never raises on BQ failure
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Default to disabled for module import; individual tests re-enable.
os.environ.setdefault("SCORING_COST_LOG_DISABLED", "true")

from src.cost_logger import (
    _lookup_cost,
    estimate_cost_usd,
    extract_tokens,
    log_llm_call,
)


class TestCostLookup(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(_lookup_cost("gpt-5-mini"), (0.00025, 0.00200))
        self.assertEqual(_lookup_cost("gpt-5"), (0.00125, 0.01000))

    def test_prefix_match_variant(self):
        # gpt-4o-2024-08-06 should fall back to gpt-4o rates
        self.assertEqual(_lookup_cost("gpt-4o-2024-08-06"), (0.00250, 0.01000))

    def test_longest_prefix_wins(self):
        # 'gpt-5-mini-snapshot-2026' must match 'gpt-5-mini', not 'gpt-5'
        self.assertEqual(_lookup_cost("gpt-5-mini-snapshot-2026"), (0.00025, 0.00200))

    def test_unknown_returns_none(self):
        self.assertIsNone(_lookup_cost("anthropic-claude-foo"))


class TestEstimateCost(unittest.TestCase):
    def test_basic_estimate(self):
        # gpt-5-mini: $0.00025/1k input, $0.002/1k output
        # 1000 in / 1000 out = 0.00025 + 0.002 = 0.00225
        self.assertEqual(estimate_cost_usd("gpt-5-mini", 1000, 1000), 0.00225)

    def test_zero_tokens(self):
        self.assertEqual(estimate_cost_usd("gpt-5-mini", 0, 0), 0.0)

    def test_unknown_model_returns_none(self):
        self.assertIsNone(estimate_cost_usd("nope", 100, 100))


class TestExtractTokens(unittest.TestCase):
    def test_responses_api_shape(self):
        resp = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=1234, output_tokens=567, total_tokens=1801)
        )
        self.assertEqual(extract_tokens(resp), (1234, 567))

    def test_chat_completions_shape(self):
        resp = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=300, total_tokens=2300)
        )
        self.assertEqual(extract_tokens(resp), (2000, 300))

    def test_no_usage_returns_zero(self):
        resp = SimpleNamespace(usage=None)
        self.assertEqual(extract_tokens(resp), (0, 0))

    def test_missing_usage_attribute_returns_zero(self):
        # Bare object with no .usage at all
        self.assertEqual(extract_tokens(object()), (0, 0))


class TestLogLlmCall(unittest.TestCase):
    def test_disabled_short_circuits_no_bq_io(self):
        """When SCORING_COST_LOG_DISABLED=true, no BQ client should ever be touched."""
        with patch.dict(os.environ, {"SCORING_COST_LOG_DISABLED": "true"}, clear=False):
            with patch("src.cost_logger._get_bq_target") as mock_target:
                resp = SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=20)
                )
                log_llm_call(
                    meeting_id="m1",
                    scoring_domain="client",
                    model="gpt-5-mini",
                    prompt_label="opportunity_now",
                    response=resp,
                )
                mock_target.assert_not_called()

    def test_writes_row_with_expected_fields(self):
        """A successful write goes through insert_rows_json with the right row shape."""
        with patch.dict(os.environ, {"SCORING_COST_LOG_DISABLED": "false"}, clear=False):
            mock_client = MagicMock()
            mock_client.insert_rows_json.return_value = []  # no errors
            with patch("src.cost_logger._get_bq_target", return_value=(
                mock_client, "proj.ds.scoring_cost_log"
            )):
                resp = SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=100, output_tokens=200)
                )
                log_llm_call(
                    meeting_id="meeting-xyz",
                    scoring_domain="talent",
                    model="gpt-5-mini",
                    prompt_label="talent_extraction",
                    response=resp,
                )

                mock_client.insert_rows_json.assert_called_once()
                args, _ = mock_client.insert_rows_json.call_args
                table_ref, rows = args
                self.assertEqual(table_ref, "proj.ds.scoring_cost_log")
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["meeting_id"], "meeting-xyz")
                self.assertEqual(row["scoring_domain"], "talent")
                self.assertEqual(row["model"], "gpt-5-mini")
                self.assertEqual(row["prompt_label"], "talent_extraction")
                self.assertEqual(row["tokens_in"], 100)
                self.assertEqual(row["tokens_out"], 200)
                # cost = 100*0.00025/1000 + 200*0.002/1000 = 0.000025 + 0.0004 = 0.000425
                self.assertAlmostEqual(row["cost_estimate_usd"], 0.000425, places=6)
                self.assertIn("log_id", row)
                self.assertIn("scored_at", row)

    def test_bq_failure_does_not_raise(self):
        """Best-effort: a BQ error must not propagate to the caller."""
        with patch.dict(os.environ, {"SCORING_COST_LOG_DISABLED": "false"}, clear=False):
            with patch("src.cost_logger._get_bq_target", side_effect=RuntimeError("BQ down")):
                resp = SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=20)
                )
                # Should NOT raise
                log_llm_call(
                    meeting_id="m1",
                    scoring_domain="client",
                    model="gpt-5-mini",
                    prompt_label="anything",
                    response=resp,
                )

    def test_insert_errors_are_warned_not_raised(self):
        """If insert_rows_json returns errors, log_llm_call should warn but not raise."""
        with patch.dict(os.environ, {"SCORING_COST_LOG_DISABLED": "false"}, clear=False):
            mock_client = MagicMock()
            mock_client.insert_rows_json.return_value = [{"error": "bad row"}]
            with patch("src.cost_logger._get_bq_target", return_value=(
                mock_client, "proj.ds.scoring_cost_log"
            )):
                resp = SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=20)
                )
                log_llm_call(
                    meeting_id="m1",
                    scoring_domain="client",
                    model="gpt-5-mini",
                    prompt_label="opportunity_now",
                    response=resp,
                )
                # Did try to insert
                mock_client.insert_rows_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
