"""
Tests for source-aware scorer routing.

Covers:
- resolve_source: extracting the routing source from GCS custom metadata
- get_scorer: dispatching to the right scorer (or raising)
- CloudEvent dispatch: the composition of the two, mocking the GCS blob
- process_pipeline: end-to-end guarantee that talent/garbage sources
  raise before any BigQuery write happens
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.router import resolve_source, get_scorer


class TestResolveSource(unittest.TestCase):
    def test_none_metadata_defaults_to_client(self):
        self.assertEqual(resolve_source(None), "client")

    def test_empty_metadata_defaults_to_client(self):
        self.assertEqual(resolve_source({}), "client")

    def test_explicit_client(self):
        self.assertEqual(resolve_source({"source": "client"}), "client")

    def test_explicit_talent(self):
        self.assertEqual(resolve_source({"source": "talent"}), "talent")

    def test_missing_source_key_defaults_to_client(self):
        self.assertEqual(resolve_source({"other": "value"}), "client")

    def test_empty_string_value_defaults_to_client(self):
        self.assertEqual(resolve_source({"source": ""}), "client")

    def test_whitespace_only_value_defaults_to_client(self):
        self.assertEqual(resolve_source({"source": "   "}), "client")

    def test_none_value_defaults_to_client(self):
        self.assertEqual(resolve_source({"source": None}), "client")

    def test_value_is_stripped_and_lowercased(self):
        self.assertEqual(resolve_source({"source": "  CLIENT  "}), "client")
        self.assertEqual(resolve_source({"source": "Talent"}), "talent")

    def test_unknown_value_passes_through(self):
        # resolve_source doesn't validate — that's get_scorer's job
        self.assertEqual(resolve_source({"source": "garbage"}), "garbage")


class TestGetScorer(unittest.TestCase):
    @patch("src.router.ClientScorer")
    def test_client_returns_client_scorer(self, mock_scorer_cls):
        scorer = get_scorer("client", model="gpt-5-mini")
        mock_scorer_cls.assert_called_once_with(model="gpt-5-mini")
        self.assertIs(scorer, mock_scorer_cls.return_value)

    def test_talent_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError) as ctx:
            get_scorer("talent")
        self.assertIn("talent", str(ctx.exception).lower())

    def test_unknown_source_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_scorer("garbage")
        self.assertIn("garbage", str(ctx.exception))

    def test_empty_string_raises_value_error(self):
        # Defensive — resolve_source defaults empties to "client", but if
        # something else feeds get_scorer directly, an empty string is invalid.
        with self.assertRaises(ValueError):
            get_scorer("")


class TestCloudEventDispatch(unittest.TestCase):
    """
    Compose resolve_source + get_scorer the way the CloudEvent handler does:
    given a GCS blob's .metadata, the routing must reach the right scorer
    (or raise loudly without instantiating anything).
    """

    @staticmethod
    def _blob(metadata):
        blob = MagicMock()
        blob.metadata = metadata
        return blob

    @patch("src.router.ClientScorer")
    def test_explicit_client_metadata_routes_to_client_scorer(self, mock_scorer_cls):
        blob = self._blob({"source": "client"})
        scorer = get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_scorer_cls.assert_called_once_with(model="gpt-5-mini")
        self.assertIs(scorer, mock_scorer_cls.return_value)

    @patch("src.router.ClientScorer")
    def test_no_metadata_defaults_to_client_scorer(self, mock_scorer_cls):
        blob = self._blob(None)
        scorer = get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_scorer_cls.assert_called_once_with(model="gpt-5-mini")
        self.assertIs(scorer, mock_scorer_cls.return_value)

    @patch("src.router.ClientScorer")
    def test_talent_metadata_raises_and_never_instantiates_scorer(self, mock_scorer_cls):
        blob = self._blob({"source": "talent"})
        with self.assertRaises(NotImplementedError):
            get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_scorer_cls.assert_not_called()

    @patch("src.router.ClientScorer")
    def test_garbage_metadata_raises_and_never_instantiates_scorer(self, mock_scorer_cls):
        blob = self._blob({"source": "weird-value"})
        with self.assertRaises(ValueError):
            get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_scorer_cls.assert_not_called()


class TestProcessPipelineRoutingGuarantee(unittest.TestCase):
    """
    End-to-end guarantee against main.process_pipeline: when source resolves
    to talent or garbage, the BigQuery upload is never reached.

    Mocks GCSClient, importer, ClientScorer and the BQ upload coroutine so the
    pipeline only exercises the routing branch.
    """

    def _run_pipeline(self, blob_metadata):
        """Drive process_pipeline once with a mocked GCS blob and assert
        whether BQ upload was called. Returns the BQ upload mock for caller
        assertions and the captured processing status."""
        import main as main_module

        # Mock GCS client + blob
        mock_blob = MagicMock()
        mock_blob.metadata = blob_metadata
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs = MagicMock()
        mock_gcs.bucket = mock_bucket
        mock_gcs.get_cached_score.return_value = None
        mock_gcs.download_to_temp_file.return_value = "/tmp/fake-transcript.txt"
        mock_gcs.cleanup_temp_files.return_value = None

        # Prime processing_status so process_pipeline can update it
        meeting_id = "test-meeting-id"
        from main import ProcessingStatus
        main_module.processing_status[meeting_id] = ProcessingStatus(
            meeting_id=meeting_id, status="pending"
        )

        with patch.object(main_module, "GCSClient", return_value=mock_gcs), \
             patch.object(main_module, "GranolaDriveImporter") as mock_granola, \
             patch.object(main_module, "PlaintextImporter") as mock_plaintext, \
             patch("src.router.ClientScorer") as mock_scorer_cls, \
             patch.object(main_module, "upload_new_format_to_bigquery",
                          new_callable=AsyncMock) as mock_bq:

            # Importers return a parseable transcript stub
            transcript_stub = SimpleNamespace(
                meeting_id=meeting_id, granola_note_id=None
            )
            mock_granola.return_value.parse_file.return_value = transcript_stub
            mock_plaintext.return_value.parse_file.return_value = transcript_stub

            # Scorer mock for the client-success path. Use SimpleNamespace so
            # the score-result object has a real __dict__ (process_pipeline
            # passes new_score_result.__dict__ to gcs.cache_score).
            score_result = SimpleNamespace(total_qualified_sections=5)
            mock_scorer = MagicMock()
            mock_scorer.score_transcript_new.return_value = score_result
            mock_scorer_cls.return_value = mock_scorer

            asyncio.run(main_module.process_pipeline(
                bucket="unknown-brain-transcripts",
                file_path="transcripts/test.txt",
                model="gpt-5-mini",
                meeting_id=meeting_id,
            ))

            status = main_module.processing_status[meeting_id]
            return status, mock_bq, mock_scorer_cls

    def test_client_source_reaches_scorer(self):
        status, mock_bq, mock_scorer_cls = self._run_pipeline({"source": "client"})
        mock_scorer_cls.assert_called_once()  # ClientScorer was instantiated

    def test_no_metadata_defaults_to_client_and_reaches_scorer(self):
        status, mock_bq, mock_scorer_cls = self._run_pipeline(None)
        mock_scorer_cls.assert_called_once()

    def test_talent_source_fails_without_bigquery_write(self):
        status, mock_bq, mock_scorer_cls = self._run_pipeline({"source": "talent"})
        self.assertEqual(status.status, "failed")
        self.assertIn("talent", (status.error or "").lower())
        mock_bq.assert_not_called()
        mock_scorer_cls.assert_not_called()

    def test_garbage_source_fails_without_bigquery_write(self):
        status, mock_bq, mock_scorer_cls = self._run_pipeline({"source": "weird"})
        self.assertEqual(status.status, "failed")
        mock_bq.assert_not_called()
        mock_scorer_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
