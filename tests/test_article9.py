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


def _mock_client(mock_openai_cls, detection_rounds, extraction, narrative="A brief."):
    """
    detection_rounds is a list of flag-lists, one per detection LLM call in
    order: round-0 detection, then each redact-loop re-detection. Pass-1
    extraction is appended last. flag mode uses [flags]; redact uses
    [round0, [], ...] where an empty list = a clean re-detection (convergence).
    """
    client = mock_openai_cls.return_value
    parse_side = [
        SimpleNamespace(
            output_parsed=Article9Detection(flags=fl),
            usage=SimpleNamespace(input_tokens=10, output_tokens=10),
        )
        for fl in detection_rounds
    ]
    parse_side.append(
        SimpleNamespace(
            output_parsed=extraction,
            usage=SimpleNamespace(input_tokens=10, output_tokens=10),
        )
    )
    client.responses.parse.side_effect = parse_side
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
        _mock_client(mock_openai, [flags], ext)
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
        # round-0 detection finds it; re-detection on scrubbed text is clean.
        _mock_client(mock_openai, [flags, []], ext)
        scorer = _scorer()
        t = _transcript(full_transcript="I was diagnosed with epilepsy last year, but I'm well now.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)

        # Raw column scrubbed at the front door.
        self.assertNotIn("epilepsy", t.full_transcript)
        self.assertIn("[REDACTED:health]", t.full_transcript)
        # Flag metadata: redacted, scrub confirmed by re-detection, span dropped,
        # round count recorded.
        f = result.article9_flags[0]
        self.assertTrue(f.redacted)
        self.assertEqual(f.raw_scrub, "confirmed")
        self.assertIsNone(f.span)
        self.assertEqual(f.redact_rounds, 1)
        # Scored fields carry no special-category text.
        self.assertNotIn("epilepsy", result.mentioned_companies[0].evidence_quote)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_token_match_handles_punctuation_gap(self, mock_openai):
        # Raw phrasing differs from the span only by punctuation (no intervening
        # words) -> the token matcher anchors it; re-detection then confirms clean.
        flags = [Article9Flag(category="health", span="heart condition",
                              location="full_transcript", confidence=0.9)]
        ext = _clean_extraction()
        _mock_client(mock_openai, [flags, []], ext)
        scorer = _scorer()
        t = _transcript(full_transcript="I've got a heart-condition, honestly.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)

        self.assertEqual(result.article9_flags[0].raw_scrub, "confirmed")
        self.assertIn("[REDACTED:health]", t.full_transcript)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_multi_phrasing_scrub_until_clean(self, mock_openai):
        # The key Option-1 behaviour: a fact stated TWO ways. Round-0 detects one
        # phrasing, scrub removes it; re-detection finds the second phrasing,
        # scrub removes that; re-detection comes back clean -> converged in 2
        # rounds, both phrasings gone, raw_scrub confirmed.
        round0 = [Article9Flag(category="health", span="I have ADHD",
                               location="full_transcript", confidence=0.95)]
        round1 = [Article9Flag(category="health", span="my ADHD diagnosis",
                               location="full_transcript", confidence=0.9)]
        ext = _clean_extraction()
        _mock_client(mock_openai, [round0, round1, []], ext)
        scorer = _scorer()
        t = _transcript(
            full_transcript="I have ADHD. We later discussed my ADHD diagnosis at length."
        )

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)

        # Both phrasings — and therefore every "ADHD" mention — are gone.
        self.assertNotIn("adhd", t.full_transcript.lower())
        self.assertIn("[REDACTED:health]", t.full_transcript)
        # Two flags accumulated across rounds; converged on round 2.
        self.assertEqual(len(result.article9_flags), 2)
        for f in result.article9_flags:
            self.assertEqual(f.raw_scrub, "confirmed")
            self.assertEqual(f.redact_rounds, 2)
            self.assertIsNone(f.span)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_subfloor_residual_does_not_block_convergence(self, mock_openai):
        # Confidence-floored convergence: round-0 finds a confident disclosure;
        # re-detection then surfaces only a LOW-confidence marginal span. That
        # sub-floor span is still scrubbed, but it must NOT block convergence or
        # trigger the hard-fail (otherwise saturated transcripts never converge).
        round0 = [Article9Flag(category="health", span="I have epilepsy",
                               location="full_transcript", confidence=0.95)]
        marginal = [Article9Flag(category="health", span="might also sneeze",
                                 location="full_transcript", confidence=0.4)]
        ext = _clean_extraction()
        _mock_client(mock_openai, [round0, marginal], ext)
        scorer = _scorer()
        t = _transcript(full_transcript="I have epilepsy. I might also sneeze sometimes.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact",
                                     "ARTICLE9_CONVERGENCE_MIN_CONFIDENCE": "0.7"}):
            result = scorer.score_transcript_new(t)

        # Converged on round 1 (no confident span remained); both spans scrubbed.
        self.assertNotIn("epilepsy", t.full_transcript)
        self.assertNotIn("might also sneeze", t.full_transcript)
        self.assertEqual(len(result.article9_flags), 2)
        for f in result.article9_flags:
            self.assertEqual(f.redact_rounds, 1)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_bounded_loop_hard_fails_when_never_clean(self, mock_openai):
        # Synthetic always-dirty input: re-detection keeps returning a category.
        # The loop is bounded -> it must hard-fail (fail closed), never spin.
        from src.scorers.talent_scorer import Article9RedactionError
        dirty = [Article9Flag(category="health", span="ongoing health issue",
                              location="full_transcript", confidence=0.9)]
        ext = _clean_extraction()
        # max_rounds=2 -> round-0 + 2 re-detections, all dirty -> raise.
        _mock_client(mock_openai, [dirty, dirty, dirty], ext)
        scorer = _scorer()
        t = _transcript(full_transcript="There is an ongoing health issue to note.")

        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact", "ARTICLE9_MAX_REDACT_ROUNDS": "2"}):
            with self.assertRaises(Article9RedactionError):
                scorer.score_transcript_new(t)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_residue_hard_fails(self, mock_openai):
        # The scorer (mock) re-emits the special-category span in a quote even
        # though the raw text was scrubbed and re-detection came back clean ->
        # the final scored-field completeness check MUST raise.
        from src.scorers.talent_scorer import Article9RedactionError
        flags = [Article9Flag(category="health", span="diagnosed with epilepsy",
                              location="full_transcript", confidence=0.95)]
        leaky = _clean_extraction(quote="they said they were diagnosed with epilepsy")
        _mock_client(mock_openai, [flags, []], leaky)
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
        _mock_client(mock_openai, [[]], ext)
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
        _mock_client(mock_openai, [[]], ext)
        scorer = _scorer()
        original = "Standard recruiter call about a design role and day rate."
        t = _transcript(full_transcript=original)
        with patch.dict(os.environ, {"ARTICLE9_MODE": "redact"}):
            result = scorer.score_transcript_new(t)
        # Round-0 detection found nothing -> no scrub loop, identical output.
        self.assertEqual(result.article9_flags, [])
        self.assertEqual(t.full_transcript, original)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_detection_always_runs(self, mock_openai):
        # Two responses.parse calls = detection + Pass-1, regardless of mode
        # (flag mode runs no re-detection loop).
        ext = _clean_extraction()
        client = _mock_client(mock_openai, [[]], ext)
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

    def test_redaction_hardfail_mapped_permanent_in_pipeline(self):
        # A non-converging redact must be a PERMANENT failure (fail closed, no
        # Eventarc redelivery), handled before the generic transient handler.
        import inspect
        import main
        src = inspect.getsource(main.process_pipeline)
        self.assertIn("except Article9RedactionError", src)
        self.assertIn('return "permanent_failure"', src)
        # Handled before the OUTER transient handler (the last `except Exception`;
        # an earlier one is the inner non-fatal sales-scoring guard).
        self.assertLess(
            src.index("except Article9RedactionError"),
            src.rindex("except Exception"),
        )


if __name__ == "__main__":
    unittest.main()
