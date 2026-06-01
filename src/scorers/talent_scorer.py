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
#
# Output budget needs to cover the whole structured extraction JSON for a
# real meeting (talent_now + triggers + motivation + market + leads +
# narrative + mentioned_companies/perception_themes/articulated_blockers,
# each with verbatim evidence_quote strings). 4000 tokens was empirically
# too tight on a 10KB transcript — saw truncation mid-string. 8000 gives
# headroom and is still ~$0.02/call on gpt-5-mini.
# Pass-1 max output must cover reasoning tokens + the structured payload. On
# the Responses API, reasoning tokens count against max_output_tokens, so when
# we raise reasoning effort (below) we must raise this too or the structured
# JSON truncates mid-string. 16000 leaves comfortable room for medium-effort
# reasoning (~few thousand tokens) plus a ~1-2k-token extraction.
TALENT_DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("TALENT_LLM_MAX_TOKENS", "16000"))
TALENT_NARRATIVE_MAX_OUTPUT_TOKENS = int(os.getenv("TALENT_NARRATIVE_MAX_TOKENS", "800"))

# Reasoning effort for Pass-1 structured extraction. The comp disambiguation
# ("is this transcript number garbled? does the summary have a coherent
# version?") is a genuine reasoning task; at `minimal` it fired only ~60% of
# the time at batch scale. `medium` gives the model room to actually do the
# cross-reference. Narrative (Pass 2) stays minimal — it's prose synthesis,
# not reasoning. Env-overridable so we can dial it back if cost/latency bites.
TALENT_PASS1_REASONING_EFFORT = os.getenv("TALENT_PASS1_REASONING_EFFORT", "medium")


SYSTEM_INSTRUCTION_PASS1 = """\
You analyse recruiter-to-candidate conversation transcripts and extract structured intelligence about the candidate, their current employer, their motivation to move, and any companies or perceptions they articulate.

Rules:
- Only return facts supported by the transcript. If a field cannot be inferred, set it to null (Optional fields) or an empty list (List fields).
- Your source of truth is the actual conversation — the section labelled "Full transcript" (or "Conversation notes" when no transcript is available). Extract ALL factual detail from there: comp figures, dates, notice periods, company names, etc. Treat the transcript as authoritative for coverage and quotes, and NEVER treat the absence of a detail from any summary as evidence it wasn't said.
- A meeting may also include an "Enhanced notes" section — Granola's AI summary. It is a SECONDARY REFERENCE with exactly one job: fixing NUMERIC values (comp, rates, salaries) that the transcript renders garbled or ambiguous. Automatic speech recognition routinely mangles spoken numbers. For EVERY comp/rate/salary figure, before you record it: if the transcript value looks implausible or unanchored for a professional context, you MUST check the Enhanced notes for the same figure and use the Enhanced notes' coherent value. Treat these as garbled and defer to the notes:
    • decimal-place errors — transcript "standard is $4.50" + notes "Rate: £450/day" → record "£450/day"; transcript "$1.25 an hour" + notes "$125/hour" → record "$125/hour"; transcript "$1.30" + notes "$130/hour" → record "$130/hour".
    • spoken number-words — transcript "I sit around four fifty" + notes "£450/day" → record "£450/day".
    • bare numbers with no currency/scale — transcript "upwards of 30" + notes "£30k" → record "£30k"; transcript "45 up to 50" + notes "£45K-50K" → record "£45K-50K".
  Only when the Enhanced notes have NO version of that figure does the raw transcript value stand. The evidence_quote always stays the transcript's own words (even if garbled). Do NOT import any non-numeric fact (company, role, motivation, etc.) that appears only in the Enhanced notes — the licence to use the notes is for numeric VALUES only.
- All `evidence_quote` fields must be VERBATIM from the actual conversation (the "Full transcript" / "Conversation notes" section) — copy the candidate's or recruiter's own words exactly. NEVER quote, paraphrase, or lift a phrase from the Enhanced notes summary. This holds even when you took a numeric VALUE from the Enhanced notes: the value may be the disambiguated figure, but the `evidence_quote` must still be the candidate's own words from the transcript (even if those words contain the garbled number).
- Use only the values defined by the controlled vocabularies for Literal-typed fields.
- `talent_triggers` should be 1-3 short phrases describing the top reasons the candidate is open to moving. If they are not actively open, return an empty list.
- `talent_market.openness_to_move` uses a 1–5 scale: 1=not looking at all, 2=passive, 3=open if right opportunity arrives, 4=actively considering, 5=actively interviewing. Use the integer that best fits; null if not inferable.

Employment status (`talent_now.employment_status`):
Determine the candidate's current employment status:
- `employed` — currently in a role (perm or freelance-on-gig). Populate `company_*` fields normally.
- `between_roles` — just wrapped a contract, recently laid off, not currently engaged. Set all `company_*` fields and `current_employer_hiring_signal` to null. Do not back-fill from their most-recent employer.
- `on_leave` — currently on parental/maternity/paternity leave or another planned career pause. The `company_*` fields should reference the employer they're on leave from. This is the one case where the most-recent employer values are correct.

Companies-vs-people rule (applies to talent_leads.companies_mentioned AND mentioned_companies AND perception_themes.company_name AND articulated_blockers.company_name when populated):
- INCLUDE: legal entities only — agencies, brands, employers, studios, clients, competitors, named platforms (e.g. YouTube, Spotify), holding groups.
- EXCLUDE: personal names of individuals (e.g. "Sarah", "Alex Crowell", "Ben"). Names of people are NEVER companies, even when mentioned as connectors or referrals.
- If a person works at a named company, record the COMPANY, not the person.
- If you can't tell whether a name refers to a person or a company, exclude it.

Alias deduplication:
- If the same entity appears under multiple spellings in the transcript (e.g. "HYDP" and "Hyde Park", or "WK" and "Wieden+Kennedy"), emit ONE entry using the most complete / canonical form you see. Do not duplicate.

Source attribution (mentioned_companies AND perception_themes):
- For each entry, set `source="candidate"` if the perception comes from the candidate's own words, or `source="recruiter"` if the recruiter made the statement. If both speakers express the same view independently, prefer `"candidate"`. The `evidence_quote` should be from whichever speaker the `source` indicates.

Articulated blockers without a named company:
- Not all blockers are anchored to a named company. Role-shaped blockers ("I don't want to be a middle person"), discipline-shaped ("I won't do web design"), category-shaped ("I'm done with classic advertising agencies"), or condition-shaped ("I can't work UK hours") have no named company. In those cases, set `company_name` to null and use the `category` value that best describes the blocker class. If a blocker truly references a specific named company, populate `company_name` as before. Do NOT invent or fabricate a company name to fill the field.
"""

PROMPT_PASS1 = """\
Extract structured talent intelligence from the meeting transcript below.

Six buckets to populate:
  1. talent_now — who they are: role, seniority, company_type, company_lifecycle,
     company_discipline, company_industry, current_employer_hiring_signal (boolean),
     employment_status (employed | between_roles | on_leave — see system instructions).
  2. talent_triggers — 1-3 short phrases on the top reasons they're open to moving.
  3. talent_motivation — primary_driver from the controlled vocabulary
     (progression | salary | the_work | flexibility | work_life_balance |
      company_type_change | employment_type_change | benefits | location |
      leadership | remote_work) + a one-line `better_description` on what
     'better' looks like + `employment_preference`.
     `employment_preference` — does the candidate want permanent employment,
     freelance, contract, or are they open to either? Use `open` only when
     explicitly indifferent. Null if not articulated.
     Use `employment_type_change` as the primary_driver when the candidate's
     core motivation is moving between employment types (e.g. contract →
     permanent, or permanent → freelance).
  4. talent_market — current_comp, expected_comp, notice_period, openness_to_move
     (integer 1–5; see system instructions for scale), realistic_time_to_move.

     Comp capture:
     `current_comp` is volunteered-only — the recruiter does not ask for it
     directly. Expect this field to be null on most transcripts. `expected_comp`
     is the candidate's desired/ideal figure and is the operational field.

     Capture comp verbatim as expressed by the candidate, in whatever shape
     they give it:
       - Salary — e.g. "$145k", "£80–100k". Standard perm shape.
       - Day rate — e.g. "£450/day", "$1,900/day". Common for freelance/contract.
       - Hourly rate — e.g. "$145/hour".
       - Annual freelance-income anchor + perm-equivalent — e.g.
         "I make ~$325k/year as a freelancer; perm-equivalent would be $625k".
         Record both figures and label them.
       - Posted-band reference — e.g. "the bottom of that range works". Record
         the reference and the band.
       - Equity-heavy comp — for startup/early-stage roles, capture equity/
         options references alongside cash where mentioned.

     Do not convert between shapes (no day-rate → annual conversion). Do not
     invent or fabricate comp values. Record exactly what the candidate said,
     in their words; if unclear or absent, set the field to null.

     `realistic_time_to_move` also captures explicit legal or availability
     constraints as free text — e.g. "non-compete with [employer] ends [date]",
     "needs visa sponsorship", "maternity leave ends [date]". These are hard
     gates on the move and must surface here, not be inferred downstream.
  5. talent_leads — companies_mentioned: List[str] of every COMPANY they named.
     This list is the union of legal-entity names referenced in the conversation:
     current/former employers, target companies, named competitors, agencies, brands,
     platforms. Personal names of individuals must NOT appear here.

Plus three intelligence-report extensions:
  6. mentioned_companies — one entry per UNIQUE company (deduplicate alias spellings):
     {name, type, sentiment, evidence_quote, source}.
     type ∈ client | competitor | in_house | independent | other.
     sentiment ∈ positive | negative | neutral | mixed.
     source ∈ candidate | recruiter (see system instructions).
  7. perception_themes — perceptions expressed about specific companies:
     {company_name, theme, polarity, evidence_quote, source}.
     theme ∈ brand | leadership | comp | culture | scope | ambition | flexibility | stability.
     polarity ∈ praise | concern | neutral.
     source ∈ candidate | recruiter.
  8. articulated_blockers — explicit blockers / reasons-to-leave:
     {company_name, category, evidence_quote}.
     company_name is OPTIONAL — set to null for role/discipline/category/
     condition-shaped blockers that don't reference a specific company
     (see system instructions). Do not invent a company name to fill the field.
     category ∈ comp_gap | brand | scope | leadership | stability | flexibility | other.

Reminder: people are never companies (see the companies-vs-people rule). Use null/[] when something can't be inferred. Quotes must be verbatim.
"""


SYSTEM_INSTRUCTION_PASS2 = """\
You write concise candidate briefs from structured intelligence. Output 100-200 words of plain prose, no markdown, no headers.

Cover, in this order: who they are now, what's prompting the move, what they want next, any standout blocker, and their realistic move horizon.

Interpret openness_to_move on a 1–5 scale: 1=not looking, 2=passive, 3=open if right opportunity arrives, 4=actively considering, 5=actively interviewing. Do not invent a different scale.

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
        Enforce status invariants (deterministic; not prompt-level).
        Pass 2: narrative summary from the canonicalised Pass-1 output.
        """
        context = self._format_transcript(transcript)

        # Pass 1 — structured extraction
        extraction = self._run_structured_extraction(context, transcript.meeting_id)

        # Normalise company names against the canonical mapping table
        extraction = self._canonicalise_companies(extraction)

        # Enforce employment_status invariants (defense in depth — the prompt
        # asks the model to do this, but observed v2 outputs show partial
        # obedience. A code-side cleanup guarantees cross-consumer consistency
        # downstream.)
        extraction = self._enforce_status_invariants(extraction)

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
            # Responses API (gpt-5* and o1*). Reasoning tokens count against
            # max_output_tokens, so pin effort=minimal — without it, gpt-5*
            # can burn the whole budget on hidden reasoning and truncate the
            # actual structured payload mid-string.
            combined = f"{SYSTEM_INSTRUCTION_PASS1}\n\n{user_content}"
            response = self.client.responses.parse(
                model=self.model,
                input=combined,
                text_format=TalentStructuredExtraction,
                reasoning={"effort": TALENT_PASS1_REASONING_EFFORT},
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
                reasoning={"effort": "minimal"},
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
    # Employment-status invariant enforcement
    # ---------------------------------------------------------------------
    @staticmethod
    def _enforce_status_invariants(
        extraction: TalentStructuredExtraction,
    ) -> TalentStructuredExtraction:
        """
        Deterministic post-Pass-1 cleanup of TalentNow company_* fields based
        on employment_status. The prompt asks the model to do this directly;
        observed v2 outputs (Min Choi) show partial obedience — role nulled
        correctly but company_type / company_industry leaked from the
        most-recent employer. Pass-2 already reads employment_status fine
        (narrative correctly opens "currently between roles"), but any other
        consumer reading e.g. `talent_now.company_industry` directly would
        get stale data without checking employment_status. This step makes
        that silent inconsistency impossible.

        Rules (from SCHEMA_DELTA.md §3, mirroring the Pass-1 system instruction):
          - `between_roles`: null out company_type, company_lifecycle,
            company_discipline, company_industry, and
            current_employer_hiring_signal. Keep role and seniority — those
            are candidate attributes, not employer attributes.
          - `employed`: no changes. company_* fields are correct for the
            candidate's current role.
          - `on_leave`: no changes. The prompt explicitly notes that
            company_* fields should reference the employer they're on
            leave from — this is the one case where most-recent employer
            values are the right answer.
          - None / unset: no changes. The model couldn't determine the
            status; we don't have grounds to second-guess company_* fields.
        """
        now = extraction.talent_now
        if now.employment_status == "between_roles":
            now.company_type = None
            now.company_lifecycle = None
            now.company_discipline = None
            now.company_industry = None
            now.current_employer_hiring_signal = None
        return extraction

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

        # Source roles (hybrid — see the investigation in
        # Changes/TRANSCRIPT_SOURCE_FINDINGS.md):
        #   - Full transcript: the AUTHORITATIVE source for coverage, all facts,
        #     and every verbatim evidence_quote. It carries detail the summary
        #     drops (e.g. a perm-equivalent comp figure stated late in the call).
        #   - Enhanced Notes: Granola's AI summary. It is NOT quotable and must
        #     never introduce facts absent from the transcript — BUT across 23
        #     real calls it corrected ASR-mangled NUMERIC values ~5:1 vs dropping
        #     them, and never once contradicted a clean transcript value (failure
        #     mode is omission, never corruption). So when a transcript number is
        #     garbled (decimal-place ASR like "$4.50" for a day rate, a spoken
        #     number-word, or a bare figure with no currency/scale), the summary
        #     is a reliable tie-breaker. We include it as a clearly-labelled
        #     SECONDARY reference for numeric disambiguation only.
        # When no full transcript exists, the summary becomes the primary source
        # (quotes are best-effort then); raw notes are the final fallback.
        body_chunks: list[str] = []
        has_transcript = bool(transcript.full_transcript and transcript.full_transcript.strip())
        if has_transcript:
            ft = transcript.full_transcript.strip()
            # gpt-5* has a 400k-token context window (~1.6M chars), so the
            # transcript is nowhere near the real constraint. The previous 32k
            # cap silently truncated real calls and dropped late-conversation
            # detail — e.g. a candidate's perm-equivalent comp figure stated
            # ~34k chars in was cut off, leaving comp null. Real 1:1 recruiter
            # calls run 28-43k chars observed; 120k chars (~30k input tokens,
            # ~$0.008 on gpt-5-mini) covers a long call with wide headroom and
            # is still a tiny fraction of the window. Kept as a backstop against
            # pathological inputs; override via TALENT_TRANSCRIPT_CHAR_CAP.
            cap = int(os.getenv("TALENT_TRANSCRIPT_CHAR_CAP", "120000"))
            if len(ft) > cap:
                ft = ft[:cap] + "\n...\n[Transcript truncated]"
            body_chunks.append(
                "Full transcript (the actual conversation — your AUTHORITATIVE "
                "source for facts and verbatim quotes):\n" + ft
            )
            # Secondary numeric-disambiguation reference (never quotable).
            if transcript.enhanced_notes and transcript.enhanced_notes.strip():
                body_chunks.append(
                    "Enhanced notes (Granola's AI summary — SECONDARY REFERENCE "
                    "ONLY; use solely to disambiguate garbled/ambiguous NUMERIC "
                    "values in the transcript above; never quote it and never add "
                    "facts not present in the transcript):\n"
                    + transcript.enhanced_notes.strip()
                )
        elif transcript.enhanced_notes and transcript.enhanced_notes.strip():
            body_chunks.append(
                "Enhanced notes (AI-GENERATED SUMMARY — no full transcript "
                "available; this is a paraphrase, NOT verbatim speech):\n"
                + transcript.enhanced_notes.strip()
            )
        else:
            note_lines = []
            for note in transcript.notes:
                ts = f"[{note.t}] " if note.t else ""
                spk = f"{note.speaker}: " if note.speaker else ""
                note_lines.append(f"{ts}{spk}{note.text}")
            body_chunks.append(
                "Conversation notes (speaker-tagged — your source for facts and "
                "verbatim quotes):\n" + "\n".join(note_lines)
            )

        return header + "\n" + "\n\n".join(body_chunks)
