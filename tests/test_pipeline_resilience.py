"""
Resilience contract for main.process_pipeline (the sole writer now that the
Granola poller is live).

Verifies:
  - transient scorer error  -> returns "transient_failure" AND releases the claim
    (so the handler returns non-2xx and Eventarc redelivers)
  - poison meeting_id        -> returns "permanent_failure" (handler ACKs, no retry)
  - success                  -> returns "completed"

Everything external (GCS, importer, scorer, BQ upload) is mocked.
"""
import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SCORING_COST_LOG_DISABLED", "true")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import openai

import main


def _gcs_mock(claim_won=True, cached=None):
    gcs = MagicMock()
    gcs.get_cached_score.return_value = cached
    gcs.claim_meeting.return_value = claim_won
    gcs.download_to_temp_file.return_value = Path("/tmp/realmeeting.txt")
    # blob().metadata used by resolve_source (which we patch anyway)
    blob = MagicMock()
    blob.metadata = {"source": "talent"}
    gcs.bucket.blob.return_value = blob
    return gcs


def _transcript(granola_id="real-meeting-123", meeting_id="real-meeting-123"):
    return SimpleNamespace(granola_note_id=granola_id, meeting_id=meeting_id)


class TestProcessPipelineResilience(unittest.TestCase):
    def setUp(self):
        # The handler normally seeds this; process_pipeline writes status into it.
        main.processing_status["mid"] = main.ProcessingStatus(meeting_id="mid", status="pending")

    def _run(self):
        return asyncio.run(
            main.process_pipeline("bucket", "transcripts/x.txt", "gpt-5-mini", "mid")
        )

    @patch("main.upload_talent_format_to_bigquery", new_callable=AsyncMock)
    @patch("main.get_scorer")
    @patch("main.resolve_source", return_value="talent")
    @patch("main.GranolaDriveImporter")
    @patch("main.GCSClient")
    def test_transient_failure_releases_claim_and_signals_retry(
        self, mock_gcs_cls, mock_importer_cls, mock_resolve, mock_get_scorer, mock_upload
    ):
        gcs = _gcs_mock()
        mock_gcs_cls.return_value = gcs
        mock_importer_cls.return_value.parse_file.return_value = _transcript()

        scorer = MagicMock()
        scorer.score_transcript_new.side_effect = openai.APITimeoutError(request=None)
        mock_get_scorer.return_value = scorer

        outcome = self._run()

        self.assertEqual(outcome, "transient_failure")
        gcs.release_claim.assert_called_once()          # claim released for retry
        mock_upload.assert_not_called()                 # nothing written
        self.assertEqual(main.processing_status["mid"].status, "failed")

    @patch("main.upload_talent_format_to_bigquery", new_callable=AsyncMock)
    @patch("main.get_scorer")
    @patch("main.resolve_source", return_value="talent")
    @patch("main.GranolaDriveImporter")
    @patch("main.GCSClient")
    def test_poison_meeting_id_is_permanent(
        self, mock_gcs_cls, mock_importer_cls, mock_resolve, mock_get_scorer, mock_upload
    ):
        gcs = _gcs_mock()
        mock_gcs_cls.return_value = gcs
        # granola_note_id missing AND meeting_id == temp-file stem ("realmeeting")
        mock_importer_cls.return_value.parse_file.return_value = _transcript(
            granola_id=None, meeting_id="realmeeting"
        )
        mock_get_scorer.return_value = MagicMock()

        outcome = self._run()

        self.assertEqual(outcome, "permanent_failure")
        mock_get_scorer.return_value.score_transcript_new.assert_not_called()
        mock_upload.assert_not_called()
        # poison check happens before the claim -> nothing to release
        gcs.claim_meeting.assert_not_called()

    @patch("main.upload_talent_format_to_bigquery", new_callable=AsyncMock)
    @patch("main.get_scorer")
    @patch("main.resolve_source", return_value="talent")
    @patch("main.GranolaDriveImporter")
    @patch("main.GCSClient")
    def test_cancellation_still_releases_claim(
        self, mock_gcs_cls, mock_importer_cls, mock_resolve, mock_get_scorer, mock_upload
    ):
        # A Cloud Run request timeout cancels the task -> CancelledError, which is
        # a BaseException (not Exception). The claim must still be released (via
        # finally) so the meeting isn't permanently stuck.
        gcs = _gcs_mock()
        mock_gcs_cls.return_value = gcs
        mock_importer_cls.return_value.parse_file.return_value = _transcript()
        scorer = MagicMock()
        scorer.score_transcript_new.side_effect = asyncio.CancelledError()
        mock_get_scorer.return_value = scorer

        with self.assertRaises(asyncio.CancelledError):
            self._run()
        gcs.release_claim.assert_called_once()   # released despite BaseException
        mock_upload.assert_not_called()

    @patch("main.upload_talent_format_to_bigquery", new_callable=AsyncMock)
    @patch("main.get_scorer")
    @patch("main.resolve_source", return_value="talent")
    @patch("main.GranolaDriveImporter")
    @patch("main.GCSClient")
    def test_success_returns_completed_and_keeps_claim(
        self, mock_gcs_cls, mock_importer_cls, mock_resolve, mock_get_scorer, mock_upload
    ):
        gcs = _gcs_mock()
        mock_gcs_cls.return_value = gcs
        mock_importer_cls.return_value.parse_file.return_value = _transcript()

        scorer = MagicMock()
        result = MagicMock()
        result.model_dump.return_value = {"ok": True}
        scorer.score_transcript_new.return_value = result
        mock_get_scorer.return_value = scorer

        outcome = self._run()

        self.assertEqual(outcome, "completed")
        gcs.release_claim.assert_not_called()           # success keeps the claim
        mock_upload.assert_awaited_once()
        self.assertEqual(main.processing_status["mid"].status, "completed")


if __name__ == "__main__":
    unittest.main()
