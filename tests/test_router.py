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
    def test_none_metadata_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_source(None)
        self.assertIn("source", str(ctx.exception).lower())

    def test_empty_metadata_raises(self):
        with self.assertRaises(ValueError):
            resolve_source({})

    def test_explicit_client(self):
        self.assertEqual(resolve_source({"source": "client"}), "client")

    def test_explicit_talent(self):
        self.assertEqual(resolve_source({"source": "talent"}), "talent")

    def test_missing_source_key_raises(self):
        with self.assertRaises(ValueError):
            resolve_source({"other": "value"})

    def test_empty_string_value_raises(self):
        with self.assertRaises(ValueError):
            resolve_source({"source": ""})

    def test_whitespace_only_value_raises(self):
        with self.assertRaises(ValueError):
            resolve_source({"source": "   "})

    def test_none_value_raises(self):
        with self.assertRaises(ValueError):
            resolve_source({"source": None})

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

    @patch("src.router.TalentScorer")
    def test_talent_returns_talent_scorer(self, mock_scorer_cls):
        scorer = get_scorer("talent", model="gpt-5-mini")
        mock_scorer_cls.assert_called_once_with(model="gpt-5-mini")
        self.assertIs(scorer, mock_scorer_cls.return_value)

    def test_unknown_source_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_scorer("garbage")
        self.assertIn("garbage", str(ctx.exception))

    def test_empty_string_raises_value_error(self):
        # resolve_source already raises on empty input, but get_scorer is
        # defensive too in case anything else feeds it directly.
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
    def test_no_metadata_raises_and_never_instantiates_scorer(self, mock_scorer_cls):
        blob = self._blob(None)
        with self.assertRaises(ValueError):
            get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_scorer_cls.assert_not_called()

    @patch("src.router.TalentScorer")
    @patch("src.router.ClientScorer")
    def test_talent_metadata_routes_to_talent_scorer(self, mock_client_cls, mock_talent_cls):
        blob = self._blob({"source": "talent"})
        scorer = get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_talent_cls.assert_called_once_with(model="gpt-5-mini")
        mock_client_cls.assert_not_called()
        self.assertIs(scorer, mock_talent_cls.return_value)

    @patch("src.router.ClientScorer")
    def test_garbage_metadata_raises_and_never_instantiates_scorer(self, mock_scorer_cls):
        blob = self._blob({"source": "weird-value"})
        with self.assertRaises(ValueError):
            get_scorer(resolve_source(blob.metadata), model="gpt-5-mini")
        mock_scorer_cls.assert_not_called()


class TestProcessPipelineRoutingGuarantee(unittest.TestCase):
    """
    End-to-end guarantee against main.process_pipeline:
      - client metadata routes to ClientScorer and the client BQ writer
      - talent metadata routes to TalentScorer and the talent BQ writer
      - no metadata / unknown source fail before either BQ writer is reached

    Mocks GCSClient, both importers, both scorers, and both BQ upload
    coroutines so the pipeline only exercises the dispatch branches.
    """

    def _run_pipeline(self, blob_metadata):
        """Drive process_pipeline once with a mocked GCS blob.
        Returns (status, mocks_dict) where mocks_dict exposes both BQ
        writers and both scorer classes for assertions."""
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

        meeting_id = "test-meeting-id"
        from main import ProcessingStatus
        main_module.processing_status[meeting_id] = ProcessingStatus(
            meeting_id=meeting_id, status="pending"
        )

        with patch.object(main_module, "GCSClient", return_value=mock_gcs), \
             patch.object(main_module, "GranolaDriveImporter") as mock_granola, \
             patch.object(main_module, "PlaintextImporter") as mock_plaintext, \
             patch("src.router.ClientScorer") as mock_client_cls, \
             patch("src.router.TalentScorer") as mock_talent_cls, \
             patch.object(main_module, "upload_new_format_to_bigquery",
                          new_callable=AsyncMock) as mock_client_bq, \
             patch.object(main_module, "upload_talent_format_to_bigquery",
                          new_callable=AsyncMock) as mock_talent_bq:

            transcript_stub = SimpleNamespace(
                meeting_id=meeting_id, granola_note_id=None
            )
            mock_granola.return_value.parse_file.return_value = transcript_stub
            mock_plaintext.return_value.parse_file.return_value = transcript_stub

            # Client scorer mock — produces a NewScoreResult-shaped stub
            # (has .total_qualified_sections for status update + .__dict__
            # for cache_score).
            client_score_result = SimpleNamespace(total_qualified_sections=5)
            client_scorer = MagicMock()
            client_scorer.score_transcript_new.return_value = client_score_result
            mock_client_cls.return_value = client_scorer

            # Talent scorer mock — needs .model_dump(mode='json') for cache_score
            # and no .total_qualified_sections (status uses getattr defaulting None).
            talent_score_result = MagicMock(spec_set=["model_dump"])
            talent_score_result.model_dump.return_value = {"talent_narrative": "stub"}
            talent_scorer = MagicMock()
            talent_scorer.score_transcript_new.return_value = talent_score_result
            mock_talent_cls.return_value = talent_scorer

            asyncio.run(main_module.process_pipeline(
                bucket="unknown-brain-transcripts",
                file_path="transcripts/test.txt",
                model="gpt-5-mini",
                meeting_id=meeting_id,
            ))

            status = main_module.processing_status[meeting_id]
            return status, {
                "client_scorer_cls": mock_client_cls,
                "talent_scorer_cls": mock_talent_cls,
                "client_bq": mock_client_bq,
                "talent_bq": mock_talent_bq,
            }

    def test_client_source_reaches_client_scorer_and_writer(self):
        status, m = self._run_pipeline({"source": "client"})
        self.assertEqual(status.status, "completed")
        m["client_scorer_cls"].assert_called_once()
        m["client_bq"].assert_called_once()
        m["talent_scorer_cls"].assert_not_called()
        m["talent_bq"].assert_not_called()

    def test_talent_source_reaches_talent_scorer_and_writer(self):
        status, m = self._run_pipeline({"source": "talent"})
        self.assertEqual(status.status, "completed")
        m["talent_scorer_cls"].assert_called_once()
        m["talent_bq"].assert_called_once()
        m["client_scorer_cls"].assert_not_called()
        m["client_bq"].assert_not_called()

    def test_talent_source_skips_sales_assessment(self):
        """Talent transcripts must not invoke score_salesperson."""
        status, m = self._run_pipeline({"source": "talent"})
        # Talent scorer mock is the only scorer that was called; assert
        # its score_salesperson was never invoked.
        talent_scorer = m["talent_scorer_cls"].return_value
        talent_scorer.score_salesperson.assert_not_called()

    def test_no_metadata_fails_without_bigquery_write(self):
        status, m = self._run_pipeline(None)
        self.assertEqual(status.status, "failed")
        self.assertIn("source", (status.error or "").lower())
        m["client_bq"].assert_not_called()
        m["talent_bq"].assert_not_called()
        m["client_scorer_cls"].assert_not_called()
        m["talent_scorer_cls"].assert_not_called()

    def test_garbage_source_fails_without_bigquery_write(self):
        status, m = self._run_pipeline({"source": "weird"})
        self.assertEqual(status.status, "failed")
        m["client_bq"].assert_not_called()
        m["talent_bq"].assert_not_called()
        m["client_scorer_cls"].assert_not_called()
        m["talent_scorer_cls"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
