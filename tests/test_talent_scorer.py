"""
Tests for TalentScorer.

Mocks the OpenAI client at construction time so no real network calls
happen. Covers:
  - Schema validation (good shape passes, bad Literal value fails)
  - Pass 1 invokes the structured-output API with the agreed schema
  - Pass 2 receives the Pass-1 output as context (NOT the raw transcript)
  - Company-name canonicalisation: matched names get rewritten, unmatched
    names pass through unchanged
  - Mappings are loaded once at __init__ (BQ loader only called once)
"""

import os
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Tests run without BigQuery / cost-log access.
os.environ.setdefault("SCORING_COST_LOG_DISABLED", "true")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from pydantic import ValidationError

from src.schemas import (
    Transcript,
    TalentMotivation,
    TalentNow,
    TalentMarket,
    TalentLeads,
    MentionedCompany,
    PerceptionTheme,
    ArticulatedBlocker,
    TalentStructuredExtraction,
)


def _make_extraction_stub():
    """A canonical-shaped Pass-1 stub with one company per intelligence-report
    field, where the names match the test fixture's client_mappings."""
    return TalentStructuredExtraction(
        talent_now=TalentNow(role="Head of Design", seniority="Head of"),
        talent_triggers=["stagnant progression"],
        talent_motivation=TalentMotivation(
            primary_driver="progression",
            better_description="Title plus team",
        ),
        talent_market=TalentMarket(openness_to_move=4, notice_period="3 months"),
        talent_leads=TalentLeads(companies_mentioned=["AKQA Media"]),
        mentioned_companies=[
            MentionedCompany(
                name="akqa MEDIA",  # variant — matches mappings (lowercased+stripped)
                type="competitor",
                sentiment="positive",
                evidence_quote="we love AKQA's work",
                source="candidate",
            ),
            MentionedCompany(
                name="UnmatchedCo Ltd",  # not in mappings — pass-through expected
                type="other",
                sentiment="neutral",
                evidence_quote="met some folks at UnmatchedCo",
                source="candidate",
            ),
        ],
        perception_themes=[
            PerceptionTheme(
                company_name="Wieden+Kennedy",
                theme="brand",
                polarity="praise",
                evidence_quote="WK has the best brand",
                source="candidate",
            ),
        ],
        articulated_blockers=[
            ArticulatedBlocker(
                company_name="akqa MEDIA",
                category="comp_gap",
                evidence_quote="comp is 20% below market",
            ),
        ],
    )


def _make_transcript() -> Transcript:
    return Transcript(
        meeting_id="test-talent-1",
        date=date(2026, 5, 21),
        company=None,
        participants=["Recruiter", "Candidate"],
        desk="Unknown",
        notes=[],
        source="granola_drive",
        title="Initial chat with senior designer",
        enhanced_notes="Candidate is a Head of Design at a small agency. Open to moving for progression. Mentions AKQA, Wieden+Kennedy.",
    )


class TestTalentSchemaValidation(unittest.TestCase):
    """Pydantic must enforce the controlled vocabularies."""

    def test_valid_extraction_constructs(self):
        ex = _make_extraction_stub()
        self.assertEqual(ex.talent_motivation.primary_driver, "progression")
        self.assertEqual(ex.mentioned_companies[0].type, "competitor")

    def test_invalid_primary_driver_raises(self):
        with self.assertRaises(ValidationError):
            TalentMotivation(primary_driver="unicorn_money", better_description="x")

    def test_invalid_mentioned_company_type_raises(self):
        with self.assertRaises(ValidationError):
            MentionedCompany(
                name="x", type="not-a-real-type", sentiment="positive",
                evidence_quote="y", source="candidate",
            )

    def test_invalid_perception_theme_raises(self):
        with self.assertRaises(ValidationError):
            PerceptionTheme(
                company_name="x", theme="bogus", polarity="praise",
                evidence_quote="y", source="candidate",
            )

    def test_invalid_blocker_category_raises(self):
        with self.assertRaises(ValidationError):
            ArticulatedBlocker(company_name="x", category="snake-oil", evidence_quote="y")

    def test_openness_to_move_out_of_range_raises(self):
        with self.assertRaises(ValidationError):
            TalentMarket(openness_to_move=10)

    def test_employment_type_change_is_valid_primary_driver(self):
        # Added per SCHEMA_DELTA #2 for contract→permanent moves.
        m = TalentMotivation(
            primary_driver="employment_type_change",
            better_description="Move from contracting to a permanent senior title",
        )
        self.assertEqual(m.primary_driver, "employment_type_change")

    def test_invalid_employment_preference_raises(self):
        with self.assertRaises(ValidationError):
            TalentMotivation(
                primary_driver="progression",
                better_description="x",
                employment_preference="part_time",  # not in vocab
            )

    def test_invalid_employment_status_raises(self):
        with self.assertRaises(ValidationError):
            TalentNow(employment_status="furloughed")  # not in vocab

    def test_articulated_blocker_company_name_can_be_null(self):
        # SCHEMA_DELTA #6: role/discipline/category/condition-shaped blockers
        # legitimately have no named company.
        b = ArticulatedBlocker(
            company_name=None,
            category="scope",
            evidence_quote="I'm done with classic advertising agencies",
        )
        self.assertIsNone(b.company_name)

    def test_mentioned_company_missing_source_raises(self):
        # SCHEMA_DELTA #5: source is required, not optional.
        with self.assertRaises(ValidationError):
            MentionedCompany(
                name="X", type="client", sentiment="neutral", evidence_quote="y"
            )

    def test_perception_theme_missing_source_raises(self):
        with self.assertRaises(ValidationError):
            PerceptionTheme(
                company_name="X", theme="brand", polarity="praise", evidence_quote="y"
            )


class TestTalentScorerConstruction(unittest.TestCase):
    """Constructor wires up OpenAI client and loads/normalises mappings."""

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_constructor_uses_injected_mappings(self, mock_openai):
        from src.scorers import TalentScorer

        scorer = TalentScorer(
            model="gpt-5-mini",
            client_mappings={"  AKQA Media ": "AKQA", "Wieden+Kennedy": "Wieden+Kennedy"},
        )
        # Keys must be normalised (stripped + lowercased)
        self.assertIn("akqa media", scorer._client_mappings)
        self.assertIn("wieden+kennedy", scorer._client_mappings)
        self.assertEqual(scorer._client_mappings["akqa media"], "AKQA")

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_constructor_loads_mappings_from_bq_when_not_injected(self, mock_openai):
        from src.scorers import TalentScorer

        with patch("src.bq_loader.BigQueryLoader") as mock_loader_cls:
            mock_loader = mock_loader_cls.return_value
            mock_loader.load_client_mappings.return_value = {"Acme Co.": "Acme"}

            scorer = TalentScorer(model="gpt-5-mini")

            mock_loader_cls.assert_called_once()
            mock_loader.load_client_mappings.assert_called_once()
            self.assertEqual(scorer._client_mappings.get("acme co."), "Acme")

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_constructor_tolerates_mappings_load_failure(self, mock_openai):
        """If BQ is unreachable at __init__, scoring still works with empty mappings."""
        from src.scorers import TalentScorer

        with patch("src.bq_loader.BigQueryLoader") as mock_loader_cls:
            mock_loader_cls.side_effect = RuntimeError("BQ unreachable")
            scorer = TalentScorer(model="gpt-5-mini")
            self.assertEqual(scorer._client_mappings, {})


class TestTalentScorerCanonicalisation(unittest.TestCase):
    """Exact-match alias lookup applied across the three intelligence-report fields."""

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_matched_names_rewritten_unmatched_passthrough(self, mock_openai):
        from src.scorers import TalentScorer

        scorer = TalentScorer(
            model="gpt-5-mini",
            client_mappings={"akqa media": "AKQA", "wieden+kennedy": "Wieden+Kennedy"},
        )

        canonicalised = scorer._canonicalise_companies(_make_extraction_stub())

        # mentioned_companies: matched + unmatched
        names = [m.name for m in canonicalised.mentioned_companies]
        self.assertIn("AKQA", names)
        self.assertIn("UnmatchedCo Ltd", names)
        self.assertNotIn("akqa MEDIA", names)

        # perception_themes
        self.assertEqual(canonicalised.perception_themes[0].company_name, "Wieden+Kennedy")

        # articulated_blockers
        self.assertEqual(canonicalised.articulated_blockers[0].company_name, "AKQA")

        # talent_leads.companies_mentioned deliberately NOT canonicalised
        # (per Brief 4 scope — only intelligence-report fields are normalised).
        self.assertEqual(canonicalised.talent_leads.companies_mentioned, ["AKQA Media"])

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_no_mappings_means_no_changes(self, mock_openai):
        from src.scorers import TalentScorer

        scorer = TalentScorer(model="gpt-5-mini", client_mappings={})
        before = _make_extraction_stub()
        after = scorer._canonicalise_companies(before)

        self.assertEqual(
            [m.name for m in after.mentioned_companies],
            ["akqa MEDIA", "UnmatchedCo Ltd"],
        )


class TestTalentScorerStatusInvariants(unittest.TestCase):
    """
    `_enforce_status_invariants` is a deterministic code-side guarantee that
    company_* fields don't leak from a former employer when the model marks
    a candidate as between_roles. Prompt asks the model to null these out;
    this method makes it impossible to forget.
    """

    def _build_extraction(self, **talent_now_fields):
        # Default talent_now: a fully-populated former-employer snapshot,
        # so any unintended retention is visible.
        defaults = dict(
            role="Creative Director",
            seniority="senior",
            company_type="in_house",
            company_lifecycle="scaleup",
            company_discipline="branding",
            company_industry="technology",
            current_employer_hiring_signal=True,
        )
        defaults.update(talent_now_fields)
        return TalentStructuredExtraction(
            talent_now=TalentNow(**defaults),
            talent_triggers=[],
            talent_motivation=TalentMotivation(
                primary_driver="progression", better_description="x"
            ),
            talent_market=TalentMarket(),
            talent_leads=TalentLeads(companies_mentioned=[]),
            mentioned_companies=[],
            perception_themes=[],
            articulated_blockers=[],
        )

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_between_roles_nulls_company_fields_and_keeps_role(self, _mock):
        from src.scorers import TalentScorer

        scorer = TalentScorer(model="gpt-5-mini", client_mappings={})
        ex = self._build_extraction(employment_status="between_roles")
        cleaned = scorer._enforce_status_invariants(ex)

        # Five fields nulled
        self.assertIsNone(cleaned.talent_now.company_type)
        self.assertIsNone(cleaned.talent_now.company_lifecycle)
        self.assertIsNone(cleaned.talent_now.company_discipline)
        self.assertIsNone(cleaned.talent_now.company_industry)
        self.assertIsNone(cleaned.talent_now.current_employer_hiring_signal)
        # Candidate-attribute fields untouched
        self.assertEqual(cleaned.talent_now.role, "Creative Director")
        self.assertEqual(cleaned.talent_now.seniority, "senior")
        # employment_status itself preserved
        self.assertEqual(cleaned.talent_now.employment_status, "between_roles")

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_employed_leaves_company_fields_alone(self, _mock):
        from src.scorers import TalentScorer

        scorer = TalentScorer(model="gpt-5-mini", client_mappings={})
        ex = self._build_extraction(employment_status="employed")
        cleaned = scorer._enforce_status_invariants(ex)

        self.assertEqual(cleaned.talent_now.company_type, "in_house")
        self.assertEqual(cleaned.talent_now.company_industry, "technology")
        self.assertTrue(cleaned.talent_now.current_employer_hiring_signal)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_on_leave_leaves_company_fields_alone(self, _mock):
        # The prompt explicitly notes that company_* should reference the
        # employer the candidate is on leave FROM — those values are correct.
        from src.scorers import TalentScorer

        scorer = TalentScorer(model="gpt-5-mini", client_mappings={})
        ex = self._build_extraction(employment_status="on_leave")
        cleaned = scorer._enforce_status_invariants(ex)

        self.assertEqual(cleaned.talent_now.company_type, "in_house")
        self.assertEqual(cleaned.talent_now.company_industry, "technology")
        self.assertTrue(cleaned.talent_now.current_employer_hiring_signal)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_none_status_leaves_company_fields_alone(self, _mock):
        # When the model can't determine status, we don't have grounds to null
        # company_* — leave the model's best guess in place.
        from src.scorers import TalentScorer

        scorer = TalentScorer(model="gpt-5-mini", client_mappings={})
        ex = self._build_extraction(employment_status=None)
        cleaned = scorer._enforce_status_invariants(ex)

        self.assertEqual(cleaned.talent_now.company_type, "in_house")
        self.assertEqual(cleaned.talent_now.company_industry, "technology")
        self.assertTrue(cleaned.talent_now.current_employer_hiring_signal)


class TestTalentScorerTranscriptFormatting(unittest.TestCase):
    """
    `_format_transcript` makes the actual conversation the authoritative source
    for quotes/facts. Hybrid (per the transcript-source investigation): when a
    full transcript exists, Granola's Enhanced Notes are ALSO included, but as a
    clearly-labelled SECONDARY REFERENCE for numeric disambiguation only (never
    quotable, never a source of new facts). When no transcript exists, the
    summary is the primary source, labelled as a non-verbatim summary.
    """

    def _scorer(self, mock_openai):
        from src.scorers import TalentScorer
        return TalentScorer(model="gpt-5-mini", client_mappings={})

    def _transcript(self, **kwargs):
        defaults = dict(
            meeting_id="m1", date=date(2026, 5, 29), source="granola_drive",
            participants=["Recruiter", "Candidate"], notes=[],
        )
        defaults.update(kwargs)
        return Transcript(**defaults)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_full_transcript_present_includes_notes_as_secondary_reference(self, mock_openai):
        scorer = self._scorer(mock_openai)
        t = self._transcript(
            full_transcript="Candidate: My day rate is 450 pounds a day.",
            enhanced_notes="Rate: £450/day",
        )
        out = scorer._format_transcript(t)
        # Transcript is the authoritative section
        self.assertIn("AUTHORITATIVE", out)
        self.assertIn("450 pounds a day", out)
        # Enhanced notes ARE present, but labelled as a secondary, non-quotable
        # numeric-disambiguation reference (hybrid).
        self.assertIn("SECONDARY REFERENCE", out)
        self.assertIn("£450/day", out)
        # The transcript must appear before the notes (primacy ordering)
        self.assertLess(out.index("450 pounds a day"), out.index("£450/day"))

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_enhanced_notes_only_is_labelled_as_summary(self, mock_openai):
        scorer = self._scorer(mock_openai)
        t = self._transcript(enhanced_notes="Candidate wants pure design work.")
        out = scorer._format_transcript(t)
        self.assertIn("AI-GENERATED SUMMARY", out)
        self.assertIn("Candidate wants pure design work.", out)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_raw_notes_fallback_when_no_transcript_or_summary(self, mock_openai):
        from src.schemas import Note
        scorer = self._scorer(mock_openai)
        t = self._transcript(notes=[Note(speaker="Candidate", text="I just wrapped a contract.")])
        out = scorer._format_transcript(t)
        self.assertIn("Conversation notes", out)
        self.assertIn("I just wrapped a contract.", out)

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_transcript_char_cap_applied(self, mock_openai):
        # Cap is 120k chars (raised from 32k, which truncated real calls and
        # dropped late-conversation comp). A 130k transcript should truncate;
        # a 40k one (a normal long call) must NOT.
        scorer = self._scorer(mock_openai)
        self.assertIn("[Transcript truncated]", scorer._format_transcript(
            self._transcript(full_transcript="x" * 130000)))
        self.assertNotIn("[Transcript truncated]", scorer._format_transcript(
            self._transcript(full_transcript="x" * 40000)))


class TestTalentScorerTwoPassFlow(unittest.TestCase):
    """Mock the OpenAI client end-to-end and verify the two-pass call shape."""

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_pass1_calls_responses_parse_with_pydantic_schema(self, mock_openai_cls):
        from src.scorers import TalentScorer

        # Build the OpenAI client mock — responses.parse returns an object with
        # .output_parsed set to a TalentStructuredExtraction instance.
        client = mock_openai_cls.return_value
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=_make_extraction_stub(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=200),
        )
        client.responses.create.return_value = SimpleNamespace(
            output_text="A brief candidate summary.",
            usage=SimpleNamespace(input_tokens=80, output_tokens=120),
        )

        scorer = TalentScorer(
            model="gpt-5-mini",
            client_mappings={"akqa media": "AKQA", "wieden+kennedy": "Wieden+Kennedy"},
        )
        transcript = _make_transcript()
        result = scorer.score_transcript_new(transcript)

        # Pass 1 was called exactly once, with the TalentStructuredExtraction schema
        client.responses.parse.assert_called_once()
        kwargs = client.responses.parse.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5-mini")
        self.assertIs(kwargs["text_format"], TalentStructuredExtraction)
        # The user content must include the raw transcript body
        self.assertIn("Head of Design", kwargs["input"])

        # Result composition
        self.assertEqual(result.meeting_id, transcript.meeting_id)
        self.assertEqual(result.talent_narrative, "A brief candidate summary.")
        # Canonicalisation was applied between passes
        self.assertEqual(result.mentioned_companies[0].name, "AKQA")
        self.assertEqual(result.perception_themes[0].company_name, "Wieden+Kennedy")

    @patch("src.scorers.talent_scorer.OpenAI")
    def test_pass2_receives_pass1_output_not_raw_transcript(self, mock_openai_cls):
        """Narrative pass must be fed the structured Pass-1 JSON, not the transcript."""
        from src.scorers import TalentScorer

        client = mock_openai_cls.return_value
        client.responses.parse.return_value = SimpleNamespace(
            output_parsed=_make_extraction_stub(),
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )
        client.responses.create.return_value = SimpleNamespace(
            output_text="narrative",
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )

        scorer = TalentScorer(model="gpt-5-mini", client_mappings={})
        scorer.score_transcript_new(_make_transcript())

        client.responses.create.assert_called_once()
        narrative_input = client.responses.create.call_args.kwargs["input"]
        # Must contain a serialised representation of the Pass-1 fields
        self.assertIn("talent_motivation", narrative_input)
        self.assertIn("primary_driver", narrative_input)
        # Must NOT contain the raw transcript body — that would defeat Pass 2's purpose
        self.assertNotIn("Initial chat with senior designer", narrative_input)


if __name__ == "__main__":
    unittest.main()
