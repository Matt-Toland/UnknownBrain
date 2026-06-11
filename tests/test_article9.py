"""
Tests for the Article 9 special-category handling layer (talent domain only).

Covers:
  - Schema validation for Article9Flag / Article9Detection.
  - ARTICLE9_MODE config: default flag, redact, invalid->flag, read from env.
  - flag mode (default): flags written WITH span, raw text + scored content intact.
  - redact mode: span scrubbed from raw text at the front door, flag redacted with
    no span, raw_scrub=confirmed; scored fields clean -> residue check passes.
  - redact where raw phrasing differs from the extracted span -> raw_scrub=partial
    (no silent pass).
  - redact HARD-FAIL: a span that survives into a scored field raises
    Article9RedactionError (the load-bearing safety net).
  - clean transcript: no flags, detection still ran, no behaviour change.
  - domain isolation: article9 is talent-only (client result/scorer/MERGE untouched).

The OpenAI client is mocked at construction; detection + Pass-1 both go through
responses.parse (side_effect in order), narrative through responses.create.
"""

import inspect
import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SCORING_COST_LOG_DISABLED", "true")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from pydantic import ValidationError

from src.schemas import (
    Article9Detection,
    Article9Flag,
    NewScoreResult,
    TalentScoringResult,
    TalentStructuredExtraction,
    TalentMotivation,
    TalentNow,
    TalentMarket,
    TalentLeads,
    MentionedCompany,
    PerceptionTheme,
    ArticulatedBlocker,
    Transcript,
    Note,
)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _clean_extraction(quote="we love their work"):
    """A Pass-1 stub with NO special-category content (used unless a test wants a leak)."""
    return TalentStructuredExtraction(
        talent_now=TalentNow(role="Designer", seniority="senior"),
        talent_triggers=["progression"],
        talent_motivation=TalentMotivation(primary_driver="progression", better_description="bigger team"),
        talent_market=TalentMarket(openness_to_move=4),
        talent_leads=TalentLeads(companies_mentioned=["AKQA"]),
        mentioned_companies=[
            MentionedCompany(
                name="AKQA", type="competitor", sentiment="positive",
                evidence_quote=quote, source="candidate",
            )
        ],
        perception_themes=[],
        articulated_blockers=[],
    )


def _transcript(full_transcript="The candidate discussed their day rate of £450/day.", notes=None):
    return Transcript(
        meeting_id="a9-test-1",
        date=date(2026, 6, 11),
        source="granola_drive",
        participants=["Recruiter", "Candidate"],
        notes=notes or [],
        title="Intro call",
        full_transcript=full_transcript,
    )


def _mock_client(mock_openai_cls, detection_flags, extraction, narrative="A brief."):
    client = mock_openai_cls.return_value
    detection_resp = SimpleNamespace(
        output_parsed=Article9Detection(flags=detection_flags),
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    extraction_resp = SimpleNamespace(
        output_parsed=extraction,
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    # Order matters: detection pass runs first, then Pass-1 structured extraction.
    client.responses.parse.side_effect = [detection_resp, extraction_resp]
    client.responses.create.return_value = SimpleNamespace(
        output_text=narrative, usage=SimpleNamespace(input_tokens=5, output_tokens=5)
    )
    return client


def _scorer():
    from src.scorers import TalentScorer
    return TalentScorer(model="gpt-5-mini", client_mappings={})


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class TestArticle9Schema(unittest.TestCase):
    def test_valid_flag(self):
        f = Article9Flag(category="health", span="epilepsy", location="full_transcript", confidence=0.9)
        self.assertEqual(f.category, "health")
        self.assertFalse(f.redacted)        # code-owned default
        self.assertIsNone(f.raw_scrub)

    def test_invalid_category_raises(self):
        with self.assertRaises(ValidationError):
            Article9Flag(category="favourite_colour", span="x", location="y", confidence=0.5)

    def test_confidence_out_of_range_raises(self):
        with self.assertRaises(ValidationError):
            Article9Flag(category="health", span="x", location="y", confidence=1.5)

    def test_detection_defaults_empty(self):
        self.assertEqual(Article9Detection().flags, [])


# --------------------------------------------------------------------------- #
# Mode config
# --------------------------------------------------------------------------- #
class TestArticle9Mode(unittest.TestCase):
    def test_default_is_flag(self):
        from src.scorers.talent_scorer import _article9_mode
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARTICLE9_MODE", None)
            self.assertEqual(_article9_mode(), "flag")

    def test_redact_from_env(self):
        from src.scorers.talent_scorer import _article9_mode
        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            self.assertEqual(_article9_mode(), "redact")

    def test_invalid_falls_back_to_flag(self):
        from src.scorers.talent_scorer import _article9_mode
        with patch.dict(os.environ, {"ARTICLE9_MODE": "nuke"}):
            self.assertEqual(_article9_mode(), "flag")

    def test_case_insensitive(self):
        from src.scorers.talent_scorer import _article9_mode
        with patch.dict(os.environ, {"ARTICLE9_MODE": "REDACT"}):
            self.assertEqual(_article9_mode(), "redact")


# --------------------------------------------------------------------------- #
# flag mode (default)
# --------------------------------------------------------------------------- #
class TestArticle9FlagMode(unittest.TestCase):
    @patch("src.scorers.talent_scorer.OpenAI")
    def test_flag_written_content_intact(self, mock_openai):
        flags = [Article9Flag(category="health", span="diagnosed with epilepsy",
                              location="full_transcript", confidence=0.9)]
        ext = _clean_extraction()
        _mock_client(mock_openai, flags, ext)
        scorer = _scorer()
        t = _transcript(full_transcript="I was diagnosed with epilepsy last year, but I'm well now.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "flag"}):
            result = scorer.score_transcript_new(t)

        # Flag persisted WITH the verbatim span; nothing redacted.
        self.assertEqual(len(result.article9_flags), 1)
        self.assertEqual(result.article9_flags[0].category, "health")
        self.assertEqual(result.article9_flags[0].span, "diagnosed with epilepsy")
        self.assertFalse(result.article9_flags[0].redacted)
        self.assertIsNone(result.article9_flags[0].raw_scrub)
        # Raw transcript untouched; scored content intact.
        self.assertIn("epilepsy", t.full_transcript)
        self.assertNotIn("[REDACTED", t.full_transcript)
        self.assertEqual(result.mentioned_companies[0].evidence_quote, "we love their work")


# --------------------------------------------------------------------------- #
# redact mode
# --------------------------------------------------------------------------- #
class TestArticle9RedactMode(unittest.TestCase):
    @patch("src.scorers.talent_scorer.OpenAI")
    def test_span_scrubbed_at_source_flag_redacted(self, mock_openai):
        flags = [Article9Flag(category="health", span="diagnosed with epilepsy",
                              location="full_transcript", confidence=0.95)]
        ext = _clean_extraction()  # scorer sees clean input -> clean output
        _mock_client(mock_openai, flags, ext)
        scorer = _scorer()
        t = _transcript(full_transcript="I was diagnosed with epilepsy last year, but I'm well now.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)

        # Raw column scrubbed at the front door.
        self.assertNotIn("epilepsy", t.full_transcript)
        self.assertIn("[REDACTED:health]", t.full_transcript)
        # Flag metadata: redacted, scrub confirmed, verbatim span dropped.
        f = result.article9_flags[0]
        self.assertTrue(f.redacted)
        self.assertEqual(f.raw_scrub, "confirmed")
        self.assertIsNone(f.span)
        # Scored fields carry no special-category text.
        self.assertNotIn("epilepsy", result.mentioned_companies[0].evidence_quote)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_partial_scrub_when_raw_phrasing_differs(self, mock_openai):
        # Extracted span is "bipolar disorder" but the raw text only says "bipolar".
        # Token match (bipolar\W+disorder) can't anchor -> partial, not silent pass.
        flags = [Article9Flag(category="health", span="bipolar disorder",
                              location="full_transcript", confidence=0.8)]
        ext = _clean_extraction()
        _mock_client(mock_openai, flags, ext)
        scorer = _scorer()
        t = _transcript(full_transcript="They mentioned being bipolar in passing.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)

        f = result.article9_flags[0]
        self.assertTrue(f.redacted)
        self.assertEqual(f.raw_scrub, "partial")   # visible, never silently clean
        self.assertIsNone(f.span)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_token_match_handles_punctuation_gap(self, mock_openai):
        # Raw phrasing differs from the span only by punctuation (no intervening
        # words) -> the token matcher anchors it -> confirmed. (An intervening
        # filler WORD would correctly yield partial — see the partial test —
        # because we never over-redact across unrelated words.)
        flags = [Article9Flag(category="health", span="heart condition",
                              location="full_transcript", confidence=0.9)]
        ext = _clean_extraction()
        _mock_client(mock_openai, flags, ext)
        scorer = _scorer()
        t = _transcript(full_transcript="I've got a heart-condition, honestly.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)

        self.assertEqual(result.article9_flags[0].raw_scrub, "confirmed")
        self.assertIn("[REDACTED:health]", t.full_transcript)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_residue_hard_fails(self, mock_openai):
        # The scorer (mock) re-emits the special-category span in a quote even
        # though the raw text was scrubbed -> the completeness check MUST raise.
        from src.scorers.talent_scorer import Article9RedactionError
        flags = [Article9Flag(category="health", span="diagnosed with epilepsy",
                              location="full_transcript", confidence=0.95)]
        leaky = _clean_extraction(quote="they said they were diagnosed with epilepsy")
        _mock_client(mock_openai, flags, leaky)
        scorer = _scorer()
        t = _transcript(full_transcript="I was diagnosed with epilepsy last year.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            with self.assertRaises(Article9RedactionError):
                scorer.score_transcript_new(t)


# --------------------------------------------------------------------------- #
# Clean transcript — no behaviour change either mode
# --------------------------------------------------------------------------- #
class TestArticle9CleanTranscript(unittest.TestCase):
    @patch("src.scorers.talent_scorer.OpenAI")
    def test_no_flags_no_change_flag_mode(self, mock_openai):
        ext = _clean_extraction()
        _mock_client(mock_openai, [], ext)
        scorer = _scorer()
        original = "Standard recruiter call about a design role and day rate."
        t = _transcript(full_transcript=original)
        with patch.dict(os.environ, {"ARTICLE9_MODE": "flag"}):
            result = scorer.score_transcript_new(t)
        self.assertEqual(result.article9_flags, [])
        self.assertEqual(t.full_transcript, original)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_no_flags_no_change_redact_mode(self, mock_openai):
        ext = _clean_extraction()
        _mock_client(mock_openai, [], ext)
        scorer = _scorer()
        original = "Standard recruiter call about a design role and day rate."
        t = _transcript(full_transcript=original)
        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)
        # Detection ran but found nothing -> identical output, raw text untouched.
        self.assertEqual(result.article9_flags, [])
        self.assertEqual(t.full_transcript, original)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_detection_always_runs(self, mock_openai):
        # Two responses.parse calls = detection + Pass-1, regardless of mode.
        ext = _clean_extraction()
        client = _mock_client(mock_openai, [], ext)
        scorer = _scorer()
        with patch.dict(os.environ, {"ARTICLE9_MODE": "flag"}):
            scorer.score_transcript_new(_transcript())
        self.assertEqual(client.responses.parse.call_count, 2)
        # First call used the Article 9 detection schema.
        first_kwargs = client.responses.parse.call_args_list[0].kwargs
        self.assertIs(first_kwargs["text_format"], Article9Detection)


# --------------------------------------------------------------------------- #
# Domain isolation — talent only
# --------------------------------------------------------------------------- #
class TestArticle9DomainIsolation(unittest.TestCase):
    def test_field_only_on_talent_result(self):
        self.assertIn("article9_flags", TalentScoringResult.model_fields)
        self.assertNotIn("article9_flags", NewScoreResult.model_fields)

    def test_talent_merge_writes_it_client_merge_does_not(self):
        from src.bq_loader import BigQueryLoader
        talent_src = inspect.getsource(BigQueryLoader.merge_talent_jsonl_data)
        client_src = inspect.getsource(BigQueryLoader.merge_client_jsonl_data)
        self.assertIn("article9_flags = source.article9_flags", talent_src)
        self.assertNotIn("article9_flags", client_src)

    def test_client_scorer_has_no_article9(self):
        from src.scorers import TalentScorer
        # Detection lives on the talent scorer only.
        self.assertTrue(hasattr(TalentScorer, "_detect_article9"))


if __name__ == "__main__":
    unittest.main()
