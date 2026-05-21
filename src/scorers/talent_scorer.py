"""
TalentScorer — extracts structured candidate intelligence from recruiter-to-
candidate transcripts.

Two-pass LLM flow:
    Pass 1: structured extraction (six talent buckets + three intelligence-
            report extensions) using OpenAI's structured outputs so the
            controlled vocabularies are enforced at the API level.
    Pass 2: narrative prose summary, fed the Pass-1 output as context (NOT
            the raw transcript). Pass 2 synthesises from extracted facts;
            it does not re-read the conversation.

Company names referenced in the intelligence-report fields are normalised
against the canonical client_mappings table via exact-match alias lookup
(no fuzzy matching). Unmatched names pass through unchanged.

Interface mirrors ClientScorer: same `model=` constructor arg, same
synchronous `score_transcript_new(transcript)` entry point so the
router and `main.process_pipeline` need no further special-casing.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

from ..cost_logger import log_llm_call
from ..schemas import (
    Transcript,
    TalentScoringResult,
    TalentStructuredExtraction,
)

load_dotenv()

logger = logging.getLogger(__name__)


# Model configuration — kept in lockstep with ClientScorer's MODEL_CONFIGS.
# Routing decision (Responses API vs Chat Completions) is by prefix.
TALENT_DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("TALENT_LLM_MAX_TOKENS", "4000"))
TALENT_NARRATIVE_MAX_OUTPUT_TOKENS = int(os.getenv("TALENT_NARRATIVE_MAX_TOKENS", "800"))


SYSTEM_INSTRUCTION_PASS1 = """\
You analyse recruiter-to-candidate conversation transcripts and extract structured intelligence about the candidate, their current employer, their motivation to move, and any companies or perceptions they articulate.

Rules:
- Only return facts supported by the transcript. If a field cannot be inferred, set it to null (Optional fields) or an empty list (List fields).
- All `evidence_quote` fields must be VERBATIM from the transcript — do not paraphrase.
- Use only the values defined by the controlled vocabularies for Literal-typed fields.
- `talent_triggers` should be 1-3 short phrases describing the top reasons the candidate is open to moving. If they are not actively open, return an empty list.
- `companies_mentioned` should include current/former employers, target companies, named competitors, and any agency or brand the candidate references by name.
"""

PROMPT_PASS1 = """\
Extract structured talent intelligence from the meeting transcript below.

Six buckets to populate:
  1. talent_now — who they are: role, seniority, company_type, company_lifecycle,
     company_discipline, company_industry, current_employer_hiring_signal (boolean).
  2. talent_triggers — 1-3 short phrases on the top reasons they're open to moving.
  3. talent_motivation — primary_driver from the controlled vocabulary + a one-line
     `better_description` on what 'better' looks like.
  4. talent_market — current_comp, expected_comp, notice_period, openness_to_move
     (1=not looking, 5=actively interviewing), realistic_time_to_move.
  5. talent_leads — companies_mentioned: List[str] of every company they named.

Plus three intelligence-report extensions:
  6. mentioned_companies — for each named company: {name, type, sentiment, evidence_quote}.
     type ∈ client | competitor | in_house | independent | other.
     sentiment ∈ positive | negative | neutral | mixed.
  7. perception_themes — perceptions they express about specific companies:
     {company_name, theme, polarity, evidence_quote}.
     theme ∈ brand | leadership | comp | culture | scope | ambition | flexibility | stability.
     polarity ∈ praise | concern | neutral.
  8. articulated_blockers — explicit blockers/reasons-to-leave:
     {company_name, category, evidence_quote}.
     category ∈ comp_gap | brand | scope | leadership | stability | flexibility | other.

Use null/[] when something can't be inferred. Quotes must be verbatim.
"""


SYSTEM_INSTRUCTION_PASS2 = """\
You write concise candidate briefs from structured intelligence. Output 100-200 words of plain prose, no markdown, no headers.

Cover, in this order: who they are now, what's prompting the move, what they want next, any standout blocker, and their realistic move horizon.

Do not fabricate facts. Synthesise only from the structured data you are given. If a field is null/empty, simply do not mention it.
"""

PROMPT_PASS2_TEMPLATE = """\
Structured candidate intelligence (extracted from the meeting):

{structured_json}

Write a 100-200 word brief for this candidate."""


class TalentScorer:
    """
    Two-pass candidate intelligence extractor.

    Construct once per scoring run. The instance loads client_mappings
    eagerly so the per-candidate `score_transcript_new` path doesn't
    hit BigQuery; pass `client_mappings=` directly to skip the load
    (used by tests).
    """

    # Identifies this scorer's writes in scoring_cost_log.
    _scoring_domain = "talent"

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        client_mappings: Optional[Dict[str, str]] = None,
    ):
        # Longer timeout for reasoning models, matching ClientScorer.
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=120.0)
        self.model = model or os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini")
        self.max_output_tokens = TALENT_DEFAULT_MAX_OUTPUT_TOKENS
        self.narrative_max_output_tokens = TALENT_NARRATIVE_MAX_OUTPUT_TOKENS

        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY environment variable not set")

        # Eagerly load + normalise mappings (key by lowercased+stripped variant_name).
        # Tests can inject directly to skip the BigQuery round-trip.
        if client_mappings is not None:
            self._client_mappings = {
                str(k).strip().lower(): v for k, v in client_mappings.items()
            }
        else:
            self._client_mappings = self._load_canonical_mappings()

    @staticmethod
    def _load_canonical_mappings() -> Dict[str, str]:
        """
        Load variant→canonical name mappings from BigQuery and normalise keys.

        Lazy import so unit tests can patch the loader without paying the
        BigQueryLoader instantiation cost just to construct the scorer.
        """
        try:
            from ..bq_loader import BigQueryLoader

            loader = BigQueryLoader()
            raw = loader.load_client_mappings()
        except Exception as e:
            logger.warning(f"Failed to load client mappings (proceeding without): {e}")
            return {}
        return {str(variant).strip().lower(): canonical for variant, canonical in raw.items()}

    # ---------------------------------------------------------------------
    # Public entry point — mirrors ClientScorer.score_transcript_new
    # ---------------------------------------------------------------------
    def score_transcript_new(self, transcript: Transcript) -> TalentScoringResult:
        """
        Run the two-pass talent scoring flow for a single transcript.

        Pass 1: structured extraction.
        Canonicalise company names against client_mappings.
        Pass 2: narrative summary from the canonicalised Pass-1 output.
        """
        context = self._format_transcript(transcript)

        # Pass 1 — structured extraction
        extraction = self._run_structured_extraction(context, transcript.meeting_id)

        # Normalise company names against the canonical mapping table
        extraction = self._canonicalise_companies(extraction)

        # Pass 2 — narrative summary, fed the canonicalised Pass-1 output (not the raw transcript)
        narrative = self._run_narrative_pass(extraction, transcript.meeting_id)

        return TalentScoringResult(
            meeting_id=transcript.meeting_id,
            date=transcript.date,
            talent_now=extraction.talent_now,
            talent_triggers=extraction.talent_triggers,
            talent_motivation=extraction.talent_motivation,
            talent_market=extraction.talent_market,
            talent_leads=extraction.talent_leads,
            mentioned_companies=extraction.mentioned_companies,
            perception_themes=extraction.perception_themes,
            articulated_blockers=extraction.articulated_blockers,
            talent_narrative=narrative,
            scored_at=datetime.now(timezone.utc),
            llm_model=self.model,
        )

    # ---------------------------------------------------------------------
    # Pass 1 — structured extraction via OpenAI structured outputs
    # ---------------------------------------------------------------------
    def _run_structured_extraction(
        self, context: str, meeting_id: str
    ) -> TalentStructuredExtraction:
        user_content = f"{PROMPT_PASS1}\n\nTranscript:\n{context}"

        if self.model.startswith("gpt-5") or self.model.startswith("o1"):
            # Responses API (gpt-5* and o1*)
            combined = f"{SYSTEM_INSTRUCTION_PASS1}\n\n{user_content}"
            response = self.client.responses.parse(
                model=self.model,
                input=combined,
                text_format=TalentStructuredExtraction,
                max_output_tokens=self.max_output_tokens,
            )
            parsed = response.output_parsed
        else:
            # Chat Completions parse helper (gpt-4o family + structured-output-capable variants)
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION_PASS1},
                    {"role": "user", "content": user_content},
                ],
                response_format=TalentStructuredExtraction,
            )
            parsed = response.choices[0].message.parsed

        log_llm_call(
            meeting_id=meeting_id,
            scoring_domain=self._scoring_domain,
            model=self.model,
            prompt_label="talent_extraction",
            response=response,
        )

        if parsed is None:
            raise RuntimeError(
                f"Pass 1 structured extraction returned no parsed output for meeting {meeting_id}"
            )
        return parsed

    # ---------------------------------------------------------------------
    # Pass 2 — narrative summary fed Pass-1 output
    # ---------------------------------------------------------------------
    def _run_narrative_pass(
        self, extraction: TalentStructuredExtraction, meeting_id: str
    ) -> str:
        structured_json = extraction.model_dump_json(indent=2)
        user_content = PROMPT_PASS2_TEMPLATE.format(structured_json=structured_json)

        if self.model.startswith("gpt-5") or self.model.startswith("o1"):
            combined = f"{SYSTEM_INSTRUCTION_PASS2}\n\n{user_content}"
            response = self.client.responses.create(
                model=self.model,
                input=combined,
                max_output_tokens=self.narrative_max_output_tokens,
            )
            text = (response.output_text or "").strip()
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION_PASS2},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=self.narrative_max_output_tokens,
            )
            text = (response.choices[0].message.content or "").strip()

        log_llm_call(
            meeting_id=meeting_id,
            scoring_domain=self._scoring_domain,
            model=self.model,
            prompt_label="talent_narrative",
            response=response,
        )

        if not text:
            logger.warning(
                f"Pass 2 narrative returned empty for meeting {meeting_id}; "
                f"falling back to a single-line summary stub"
            )
            text = "Candidate summary unavailable — narrative pass returned no output."
        return text

    # ---------------------------------------------------------------------
    # Company-name canonicalisation (exact-match alias lookup only)
    # ---------------------------------------------------------------------
    def _canonicalise_companies(
        self, extraction: TalentStructuredExtraction
    ) -> TalentStructuredExtraction:
        """
        Walk mentioned_companies, perception_themes, and articulated_blockers;
        replace `name` / `company_name` with the canonical form when an exact
        (case-insensitive, stripped) alias match exists. Unmatched names
        pass through unchanged.

        No fuzzy matching, no edit-distance, no heuristics — exact-match
        alias lookup only (per Brief 4 scope).
        """
        if not self._client_mappings:
            return extraction

        def canonical(name: Optional[str]) -> Optional[str]:
            if not name:
                return name
            return self._client_mappings.get(name.strip().lower(), name)

        for company in extraction.mentioned_companies:
            company.name = canonical(company.name)
        for theme in extraction.perception_themes:
            theme.company_name = canonical(theme.company_name)
        for blocker in extraction.articulated_blockers:
            blocker.company_name = canonical(blocker.company_name)
        return extraction

    # ---------------------------------------------------------------------
    # Transcript formatting
    # ---------------------------------------------------------------------
    def _format_transcript(self, transcript: Transcript) -> str:
        """
        Format the transcript for the talent extraction prompt.

        Talent transcripts come from recruiter↔candidate calls; the "Them:"/"Me:"
        speaker-role guard rails that ClientScorer uses don't apply here. The
        whole conversation is in scope and both sides are about the candidate.
        """
        header = (
            f"Meeting: {transcript.title or transcript.calendar_event_title or 'Unknown'}\n"
            f"Date: {transcript.date}\n"
            f"Participants: {', '.join(transcript.participants) if transcript.participants else 'Unknown'}\n"
        )

        # Prefer enhanced notes if present (Granola's structured output); fall back to
        # full transcript; finally fall back to raw notes.
        body_chunks: list[str] = []
        if transcript.enhanced_notes and transcript.enhanced_notes.strip():
            body_chunks.append("Enhanced notes:\n" + transcript.enhanced_notes.strip())
        if transcript.full_transcript and transcript.full_transcript.strip():
            ft = transcript.full_transcript.strip()
            # Cap to keep context manageable for non-400k-window models
            if len(ft) > 12000:
                ft = ft[:12000] + "\n...\n[Transcript truncated]"
            body_chunks.append("Full transcript:\n" + ft)
        if not body_chunks:
            note_lines = []
            for note in transcript.notes:
                ts = f"[{note.t}] " if note.t else ""
                spk = f"{note.speaker}: " if note.speaker else ""
                note_lines.append(f"{ts}{spk}{note.text}")
            body_chunks.append("Notes:\n" + "\n".join(note_lines))

        return header + "\n" + "\n\n".join(body_chunks)
