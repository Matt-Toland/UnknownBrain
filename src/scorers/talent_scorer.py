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

import re

from ..cost_logger import log_llm_call
from ..llm_retry import call_with_transient_retry
from ..schemas import (
    Article9Detection,
    Article9Flag,
    CompStructured,
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


# Plausibility bounds for structured comp, keyed by period. Comp feeds aggregate
# salary-trend stats, so the bar is "garbage excludable," not per-candidate
# precision. The ranges are deliberately wide and currency-agnostic: GBP/USD/EUR
# sit within ~1.5x of each other, so a garbled ASR figure (a £450/day rate heard
# as "$4.50", or $125/hour heard as "$1.25") falls orders of magnitude outside
# the band regardless of currency, while every real professional figure sits
# comfortably inside. Read at call time so tests / ops can override via env.
def _comp_bounds() -> Dict[str, tuple]:
    return {
        "day": (
            float(os.getenv("COMP_PLAUSIBLE_DAY_MIN", "50")),
            float(os.getenv("COMP_PLAUSIBLE_DAY_MAX", "5000")),
        ),
        "hour": (
            float(os.getenv("COMP_PLAUSIBLE_HOUR_MIN", "5")),
            float(os.getenv("COMP_PLAUSIBLE_HOUR_MAX", "500")),
        ),
        "year": (
            float(os.getenv("COMP_PLAUSIBLE_YEAR_MIN", "10000")),
            float(os.getenv("COMP_PLAUSIBLE_YEAR_MAX", "2000000")),
        ),
    }


# ---------------------------------------------------------------------------
# Article 9 special-category handling (UK GDPR Art. 9) — talent domain only.
# ---------------------------------------------------------------------------
# Detection ALWAYS runs (a dedicated pre-scoring pass on the original text);
# the mode governs only the WRITE behaviour. Read at call time so flipping the
# toggle doesn't need a redeploy and tests can patch it.
#   flag (default): nothing removed — raw columns, buckets, narrative, quotes
#       all written intact; article9_flags metadata records what/where.
#   redact: scrub detected spans from the raw text at the FRONT DOOR, before
#       scoring, so every downstream field inherits clean input by construction;
#       the verbatim span is dropped from metadata (category + location only).
ARTICLE9_VALID_MODES = ("flag", "redact")


def _article9_mode() -> str:
    mode = os.getenv("ARTICLE9_MODE", "flag").strip().lower()
    return mode if mode in ARTICLE9_VALID_MODES else "flag"


# Detection is compliance-critical recall, so default to medium reasoning. As
# with Pass-1, reasoning tokens count against max_output on the Responses API.
ARTICLE9_DETECTION_REASONING_EFFORT = os.getenv("ARTICLE9_DETECTION_REASONING_EFFORT", "medium")
ARTICLE9_DETECTION_MAX_OUTPUT_TOKENS = int(os.getenv("ARTICLE9_DETECTION_MAX_TOKENS", "16000"))

# Redact mode verifies completeness by re-detecting on the scrubbed text and
# scrubbing anything new, bounded to this many rounds. A single detected span is
# only one phrasing of a fact a candidate may repeat ("I have ADHD" vs the
# enhanced_notes "Has ADHD"); exact-span scrubbing alone leaves the other
# phrasings. The loop closes that gap; if the text is still dirty after the
# bound, we fail closed rather than persist a row re-detection still flags.
# Default 5: on a heavily-saturated transcript (a candidate whose disability is a
# recurring theme), confident disclosures are scattered across many sentences and
# drain a few per round; the Nimo diagnostic reached sub-floor by round ~4, so 5
# gives headroom. Most talent transcripts mention a category incidentally and
# converge in 1 round. The bound only bites on saturated meetings, where it
# correctly fails closed rather than grind unboundedly.
ARTICLE9_MAX_REDACT_ROUNDS = int(os.getenv("ARTICLE9_MAX_REDACT_ROUNDS", "5"))

# Convergence confidence floor. On a transcript where a category is pervasively
# discussed, the non-deterministic detector surfaces an endless tail of marginal
# detections (hyperbole "I'm dying", garbled ASR fragments, nationality≠race) —
# the genuine high-confidence disclosures scrub out in 2-3 rounds, but absolute
# zero is unreachable. So the redact loop scrubs EVERYTHING it detects, but only
# REQUIRES-clean / hard-fails on detections at/above this floor. The guarantee
# is therefore "no confident special-category disclosure survives" — precise and
# achievable — rather than "zero detections", which would fail-closed (drop the
# meeting) over noise. Validated against the Nimo transcript (4 self-disclosed
# categories): floor 0.7 cleanly separates the 0.8–0.99 disclosures from the
# ≤0.6 marginal tail.
ARTICLE9_CONVERGENCE_MIN_CONFIDENCE = float(os.getenv("ARTICLE9_CONVERGENCE_MIN_CONFIDENCE", "0.7"))


# What to do when redact mode CANNOT clean a transcript within the bound:
#   fallback (default) — store the meeting in flag behaviour (data retained +
#       flagged for manual review), never drop it. A saturated transcript keeps
#       its non-sensitive value (role/comp/companies) and is visible for handling.
#   drop — fail closed: do not store the row at all (strict no-retention).
# The choice is a controller/DPO decision; default to never-lose-a-meeting.
def _article9_on_failure() -> str:
    v = os.getenv("ARTICLE9_REDACT_ON_FAILURE", "fallback").strip().lower()
    return v if v in ("fallback", "drop") else "fallback"


class Article9RedactionError(RuntimeError):
    """
    Raised in redact mode when a detected special-category span survives the
    front-door scrub and would otherwise reach a persisted field. Fail closed:
    the scoring call aborts before any BigQuery write, so special-category data
    is never persisted in redact mode. This is the load-bearing safety check —
    in front-door redaction the scored fields are clean ONLY if the scrub
    worked, so a survivor must hard-fail, never be logged-and-ignored.
    """


SYSTEM_INSTRUCTION_ARTICLE9 = """\
You are a UK GDPR Article 9 special-category data detector. You scan a recruiter↔candidate meeting transcript and identify every span of text that reveals, or is, special-category personal data about an identifiable person.

The nine Article 9 special categories (use these exact enum values for `category`):
- racial_or_ethnic_origin
- political_opinions
- religious_or_philosophical_beliefs
- trade_union_membership
- genetic_data
- biometric_data
- health  (physical or mental health, conditions, diagnoses, disability, pregnancy, treatment, medication)
- sex_life
- sexual_orientation

Rules:
- Return one entry per distinct special-category reference, in `flags`. If there are none, return an empty list.
- `span` MUST be the VERBATIM substring from the transcript that carries the special-category information — copy it exactly as written (same casing, punctuation, filler words). Keep it tight: the minimal phrase that conveys the special-category fact, not the whole sentence. This span is used to locate and remove the text, so it must match the source exactly.
- `category` is the single best-fitting enum from the nine above.
- `location` is a short locator for where it appeared — use the section name ("full_transcript", "enhanced_notes", "my_notes", or "notes") and optionally a few words of nearby context.
- `confidence` is 0–1. Favour recall: when something plausibly reveals a special category, flag it with a lower confidence rather than dropping it.
- Detect references about ANY identifiable person in the conversation (the candidate, the recruiter, or a named third party), from either speaker.
- This is detection only. Do NOT set `redacted` or `raw_scrub` — those are computed downstream in code. Do not rewrite, summarise, or sanitise anything; only report spans.
- Do not over-reach into non-special data: generic job role, seniority, company, comp, notice period, or motivation are NOT Article 9 categories. A nationality/visa mention is only racial_or_ethnic_origin if it actually reveals racial/ethnic origin; pure work-authorisation logistics are not special-category on their own.
- IGNORE any `[REDACTED:<category>]` placeholders — they mark content already removed. Do not flag them, and do not treat the category word inside a placeholder as a new reference.
"""

PROMPT_ARTICLE9 = """\
Scan the meeting text below and return every UK GDPR Article 9 special-category span as structured `flags` (category, verbatim span, location, confidence). Return an empty list if there are none. Detection only — do not set redacted/raw_scrub, and do not alter any text.

Meeting text:
"""


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

     Structured comp: ALSO emit `current_comp_structured` and
     `expected_comp_structured` alongside the free-text strings — the parsed
     form of the SAME figure, for aggregate salary-trend reporting. Each is an
     object {currency, amount_min, amount_max, period, basis}:
       - currency ∈ GBP | USD | EUR | other — infer from the symbol (£/$/€) or
         context ("pounds", "dollars"); null only if genuinely unknowable.
       - amount_min / amount_max — the numeric value(s) in the stated unit,
         with k-suffixes expanded ("£80k" → 80000) and separators stripped
         ("$1,900" → 1900). For a single value set min = max. For a range
         ("£45–50k") set min=45000, max=50000.
       - period ∈ day | hour | year — the unit the amount is expressed in
         (day rate → day, hourly → hour, salary → year); use `other` for
         anything that doesn't fit (e.g. a pure equity reference) and null if
         no unit is stated.
       - basis — short label for what the figure covers: "base", "base+bonus",
         "total", "equity-heavy", etc. Null if not stated.
     Use the SAME disambiguated number you recorded in the free-text field (if
     you deferred to the Enhanced notes for a garbled figure, parse the
     corrected value here too). If a comp string is absent, set its
     `*_structured` to null. DO NOT set a `plausible` field — leave it out
     entirely; it is computed downstream in code, not by you.

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
        # max_retries=0: we own retries via call_with_transient_retry (bounded
        # exponential backoff) so the retry policy is explicit, testable, and the
        # SDK's default 2 retries don't compound with ours.
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=120.0, max_retries=0)
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

        Article 9: detect special-category spans on the ORIGINAL text first;
            in redact mode scrub them at the front door (before scoring) so the
            scored fields are clean by construction.
        Pass 1: structured extraction.
        Canonicalise company names against client_mappings.
        Enforce status invariants (deterministic; not prompt-level).
        Pass 2: narrative summary from the canonicalised Pass-1 output.
        """
        mode = _article9_mode()

        # Article 9 detection — ALWAYS runs (talent only), on the ORIGINAL text,
        # BEFORE scoring so redact mode can scrub at the front door.
        article9_flags = self._detect_article9(transcript)
        original_spans: list = []
        article9_status = "flag" if mode == "flag" else "redacted"

        if mode == "redact" and article9_flags:
            # Snapshot the original text + pristine flags BEFORE scrubbing, so a
            # non-convergence can fall back to flag behaviour cleanly.
            text_snapshot = self._snapshot_text(transcript)
            flag_snapshot = [f.model_copy(deep=True) for f in article9_flags]
            try:
                # Front-door scrub-until-clean: scrub, re-detect on the scrubbed
                # text, scrub anything new (bounded). Mutates the transcript IN
                # PLACE so both the scorer and the raw-column writer (same object)
                # inherit clean input. Raises Article9RedactionError if confident
                # special-category data can't be cleared within the bound.
                article9_flags, original_spans = self._redact_to_clean(
                    transcript, article9_flags
                )
            except Article9RedactionError:
                if _article9_on_failure() == "drop":
                    # Strict no-retention: fail closed, do not store the row.
                    raise
                # Fallback: never lose the meeting. Restore the original text and
                # the pristine (unredacted) flags, and store as flag behaviour —
                # data retained + flagged for manual review. Marked so it's
                # monitorable. The residue check is skipped (we deliberately
                # retained the data).
                self._restore_text(transcript, text_snapshot)
                article9_flags = flag_snapshot
                original_spans = []
                article9_status = "redact_fallback"
                logger.warning(
                    f"ARTICLE9_REDACT_FALLBACK meeting={transcript.meeting_id}: "
                    f"redaction did not converge; stored with data RETAINED + "
                    f"flagged for manual review (not dropped)."
                )

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

        # Flag structured-comp plausibility deterministically (the LLM emits the
        # parsed figures but never self-assesses plausibility — code does that, so
        # garbled ASR values are excludable from aggregates).
        extraction = self._flag_comp_plausibility(extraction)

        # Pass 2 — narrative summary, fed the canonicalised Pass-1 output (not the raw transcript)
        narrative = self._run_narrative_pass(extraction, transcript.meeting_id)

        result = TalentScoringResult(
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
            article9_flags=article9_flags,
            article9_status=article9_status,
            scored_at=datetime.now(timezone.utc),
            llm_model=self.model,
        )

        if mode == "redact" and article9_status == "redacted":
            # Load-bearing hard check (only when we actually redacted — a
            # fallback row deliberately retains the data). In front-door
            # redaction the scored fields are clean ONLY if the scrub worked —
            # if a span slipped through it flowed into the buckets/quotes/
            # narrative, and this is the only catch. Raises (fail closed) so a
            # leak is never persisted.
            self._assert_no_article9_residue(result, transcript, original_spans)

        return result

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
            response = call_with_transient_retry(
                lambda: self.client.responses.parse(
                    model=self.model,
                    input=combined,
                    text_format=TalentStructuredExtraction,
                    reasoning={"effort": TALENT_PASS1_REASONING_EFFORT},
                    max_output_tokens=self.max_output_tokens,
                ),
                label=f"talent_pass1[{meeting_id}]",
            )
            parsed = response.output_parsed
        else:
            # Chat Completions parse helper (gpt-4o family + structured-output-capable variants)
            response = call_with_transient_retry(
                lambda: self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION_PASS1},
                        {"role": "user", "content": user_content},
                    ],
                    response_format=TalentStructuredExtraction,
                ),
                label=f"talent_pass1[{meeting_id}]",
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
            response = call_with_transient_retry(
                lambda: self.client.responses.create(
                    model=self.model,
                    input=combined,
                    reasoning={"effort": "minimal"},
                    max_output_tokens=self.narrative_max_output_tokens,
                ),
                label=f"talent_pass2[{meeting_id}]",
            )
            text = (response.output_text or "").strip()
        else:
            response = call_with_transient_retry(
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION_PASS2},
                        {"role": "user", "content": user_content},
                    ],
                    max_tokens=self.narrative_max_output_tokens,
                ),
                label=f"talent_pass2[{meeting_id}]",
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
    # Article 9 — detection pass (always runs; talent domain only)
    # ---------------------------------------------------------------------
    def _detect_article9(self, transcript: Transcript) -> list:
        """
        Dedicated pre-scoring LLM pass over the ORIGINAL transcript text that
        identifies UK GDPR Article 9 special-category spans. Returns a list of
        Article9Flag (empty if none). Runs in both modes — you can't scrub what
        you haven't detected. The LLM sets category/span/location/confidence;
        `redacted`/`raw_scrub` stay at their code-owned defaults here.
        """
        meeting_id = transcript.meeting_id
        context = self._format_for_article9(transcript)
        if not context.strip():
            return []

        user_content = f"{PROMPT_ARTICLE9}{context}"

        if self.model.startswith("gpt-5") or self.model.startswith("o1"):
            combined = f"{SYSTEM_INSTRUCTION_ARTICLE9}\n\n{user_content}"
            response = call_with_transient_retry(
                lambda: self.client.responses.parse(
                    model=self.model,
                    input=combined,
                    text_format=Article9Detection,
                    reasoning={"effort": ARTICLE9_DETECTION_REASONING_EFFORT},
                    max_output_tokens=ARTICLE9_DETECTION_MAX_OUTPUT_TOKENS,
                ),
                label=f"talent_article9[{meeting_id}]",
            )
            parsed = response.output_parsed
        else:
            response = call_with_transient_retry(
                lambda: self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION_ARTICLE9},
                        {"role": "user", "content": user_content},
                    ],
                    response_format=Article9Detection,
                ),
                label=f"talent_article9[{meeting_id}]",
            )
            parsed = response.choices[0].message.parsed

        log_llm_call(
            meeting_id=meeting_id,
            scoring_domain=self._scoring_domain,
            model=self.model,
            prompt_label="talent_article9_detection",
            response=response,
        )

        if parsed is None:
            # Detection is compliance-critical: a null parse is not "no
            # special-category data", it's a failed detection. Fail loud so the
            # pipeline retries/redelivers rather than silently writing unscanned.
            raise RuntimeError(
                f"Article 9 detection returned no parsed output for meeting {meeting_id}"
            )
        return list(parsed.flags)

    def _format_for_article9(self, transcript: Transcript) -> str:
        """
        Concatenate every raw source field the talent path can persist
        (full_transcript, enhanced_notes, my_notes, speaker notes) under section
        labels, so detection sees exactly the text that could leak. Capped by
        the same env knob as scoring to guard against pathological inputs.
        """
        cap = int(os.getenv("TALENT_TRANSCRIPT_CHAR_CAP", "120000"))
        chunks: list[str] = []
        if transcript.full_transcript and transcript.full_transcript.strip():
            chunks.append("[full_transcript]\n" + transcript.full_transcript.strip())
        if transcript.enhanced_notes and transcript.enhanced_notes.strip():
            chunks.append("[enhanced_notes]\n" + transcript.enhanced_notes.strip())
        if transcript.my_notes and transcript.my_notes.strip():
            chunks.append("[my_notes]\n" + transcript.my_notes.strip())
        note_lines = [n.text for n in (transcript.notes or []) if n.text and n.text.strip()]
        if note_lines:
            chunks.append("[notes]\n" + "\n".join(note_lines))
        text = "\n\n".join(chunks)
        if len(text) > cap:
            text = text[:cap] + "\n...\n[truncated]"
        return text

    # ---------------------------------------------------------------------
    # Article 9 — front-door scrub (redact mode only; mutates in place)
    # ---------------------------------------------------------------------
    def _scrub_article9(self, transcript: Transcript, flags: list) -> None:
        """
        Remove every detected span from the transcript's raw text fields IN
        PLACE, replacing it with `[REDACTED:<category>]`. Because the scorer and
        the BQ raw-column writer both read this same object, one scrub here makes
        every downstream field clean.

        For each flag: try exact (case-insensitive) match first, then a
        whitespace/punctuation-tolerant token match (the extracted span won't
        always be verbatim — "epilepsy" vs "uh, I've got, like, epilepsy"). Set
        `raw_scrub='confirmed'` if the span was located and removed anywhere,
        else `'partial'` — an unconfirmed scrub must be VISIBLE, never silently
        assumed clean. Always set `redacted=True` and drop the verbatim `span`
        so the special-category text itself is never persisted.
        """
        for flag in flags:
            span = flag.span
            placeholder = f"[REDACTED:{flag.category}]"
            removed_anywhere = False

            if span and span.strip():
                # Raw text fields.
                if transcript.full_transcript:
                    transcript.full_transcript, hit = self._redact_span_in_text(
                        transcript.full_transcript, span, placeholder
                    )
                    removed_anywhere = removed_anywhere or hit
                if transcript.enhanced_notes:
                    transcript.enhanced_notes, hit = self._redact_span_in_text(
                        transcript.enhanced_notes, span, placeholder
                    )
                    removed_anywhere = removed_anywhere or hit
                if transcript.my_notes:
                    transcript.my_notes, hit = self._redact_span_in_text(
                        transcript.my_notes, span, placeholder
                    )
                    removed_anywhere = removed_anywhere or hit
                # Speaker notes (the no-transcript fallback source).
                for note in transcript.notes or []:
                    if note.text:
                        note.text, hit = self._redact_span_in_text(
                            note.text, span, placeholder
                        )
                        removed_anywhere = removed_anywhere or hit

            flag.raw_scrub = "confirmed" if removed_anywhere else "partial"
            flag.redacted = True
            flag.span = None  # never persist the verbatim special-category text

    @staticmethod
    def _redact_span_in_text(text: str, span: str, placeholder: str):
        """
        Replace `span` in `text` with `placeholder`. Returns (new_text, found).
        Exact case-insensitive match first; failing that, a token match tolerant
        of whitespace/punctuation between the span's words. Returns found=False
        if the span couldn't be anchored (caller records that as a partial scrub).
        """
        if not text or not span or not span.strip():
            return text, False

        # 1. Exact (case-insensitive) substring.
        exact = re.compile(re.escape(span), re.IGNORECASE)
        if exact.search(text):
            return exact.sub(placeholder, text), True

        # 2. Token match: the span's words in order, separated by any run of
        #    non-word characters. Anchors a span whose raw phrasing differs only
        #    by punctuation/whitespace; deliberately conservative (no fuzzy word
        #    edits) so we never over-redact unrelated text.
        tokens = re.findall(r"\w+", span)
        if not tokens:
            return text, False
        pattern = re.compile(r"\W+".join(re.escape(t) for t in tokens), re.IGNORECASE)
        if pattern.search(text):
            return pattern.sub(placeholder, text), True

        return text, False

    # ---------------------------------------------------------------------
    # Article 9 — text snapshot/restore (supports the flag-fallback path)
    # ---------------------------------------------------------------------
    @staticmethod
    def _snapshot_text(transcript: Transcript) -> dict:
        """Capture the raw text fields before front-door scrubbing mutates them."""
        return {
            "full_transcript": transcript.full_transcript,
            "enhanced_notes": transcript.enhanced_notes,
            "my_notes": transcript.my_notes,
            "notes": [n.text for n in (transcript.notes or [])],
        }

    @staticmethod
    def _restore_text(transcript: Transcript, snapshot: dict) -> None:
        """Restore the original raw text (used when redact falls back to flag)."""
        transcript.full_transcript = snapshot["full_transcript"]
        transcript.enhanced_notes = snapshot["enhanced_notes"]
        transcript.my_notes = snapshot["my_notes"]
        for note, text in zip(transcript.notes or [], snapshot["notes"]):
            note.text = text

    # ---------------------------------------------------------------------
    # Article 9 — scrub-until-clean loop (redact mode; HARD-FAILS on no converge)
    # ---------------------------------------------------------------------
    def _redact_to_clean(self, transcript: Transcript, flags: list):
        """
        Front-door scrub-until-clean for redact mode.

        A single detected span is only ONE phrasing of a fact a candidate may
        state several ways ("I have ADHD" in the transcript vs "Has ADHD" in the
        enhanced_notes summary). Exact-span scrubbing removes that phrasing but
        not the others, so we scrub EVERYTHING detected, then RE-DETECT on the
        scrubbed text and scrub anything new — bounded to ARTICLE9_MAX_REDACT_ROUNDS.

        Convergence is confidence-floored: a re-detection pass that returns no
        detection at/above ARTICLE9_CONVERGENCE_MIN_CONFIDENCE. On a saturated
        transcript the detector emits an endless tail of marginal (≤floor)
        detections — we still scrub those, but they don't block convergence. If
        a CONFIDENT (≥floor) detection persists after the bound, raise
        Article9RedactionError (fail closed). Mutates `transcript` in place.

        Returns (all_flags, confident_spans): every flag found across rounds
        (spans dropped, raw_scrub + redact_rounds set) and the verbatim spans of
        the CONFIDENT detections (kept in memory for the caller's final
        scored-field residue check — the hard guarantee is about confident data).
        """
        max_rounds = int(os.getenv("ARTICLE9_MAX_REDACT_ROUNDS", str(ARTICLE9_MAX_REDACT_ROUNDS)))
        floor = float(os.getenv("ARTICLE9_CONVERGENCE_MIN_CONFIDENCE", str(ARTICLE9_CONVERGENCE_MIN_CONFIDENCE)))
        all_flags = list(flags)
        confident_spans = [f.span for f in flags if f.span and f.confidence >= floor]
        self._scrub_article9(transcript, flags)

        converged = False
        rounds_used = 0
        for rnd in range(1, max_rounds + 1):
            rounds_used = rnd
            residual = self._detect_article9(transcript)
            if residual:
                # Scrub everything found (incl. sub-floor) to maximise removal.
                confident_spans.extend(
                    f.span for f in residual if f.span and f.confidence >= floor
                )
                all_flags.extend(residual)
                self._scrub_article9(transcript, residual)
            # Converged once no CONFIDENT special-category data remains.
            if not any(f.confidence >= floor for f in residual):
                converged = True
                break

        if not converged:
            raise Article9RedactionError(
                f"Article 9 redaction did not converge for meeting "
                f"{transcript.meeting_id}: re-detection still found special-category "
                f"data at confidence >= {floor} after {max_rounds} scrub round(s). "
                f"Failing closed — refusing to persist a row re-detection still "
                f"considers dirty."
            )

        # Converged: a re-detection pass found no confident special-category
        # data. Mark confirmed and record how many rounds it took (near-miss
        # visibility). raw_scrub reflects the re-detection verdict.
        for f in all_flags:
            f.raw_scrub = "confirmed"
            f.redact_rounds = rounds_used
        return all_flags, confident_spans

    # ---------------------------------------------------------------------
    # Article 9 — completeness check (redact mode; HARD-FAILS)
    # ---------------------------------------------------------------------
    def _assert_no_article9_residue(
        self, result: TalentScoringResult, transcript: Transcript, original_spans: list
    ) -> None:
        """
        Hard guarantee for redact mode: no detected special-category span
        survives into any persisted field — scored buckets, narrative, evidence
        quotes, OR the raw columns. Raises Article9RedactionError (fail closed)
        if one does, so the pipeline aborts before any BigQuery write.

        This is the load-bearing safety net: front-door scoring is clean only if
        the scrub worked, so a survivor MUST stop the write, not just log.
        Runs while `original_spans` are still in local memory (they are dropped
        from the persisted flags), so there is no other post-hoc way to verify.
        """
        if not original_spans:
            return

        haystack = "\n".join(
            [
                result.talent_narrative or "",
                json.dumps(result.talent_now.model_dump(mode="json")),
                json.dumps(result.talent_motivation.model_dump(mode="json")),
                json.dumps(result.talent_market.model_dump(mode="json")),
                json.dumps(result.talent_leads.model_dump(mode="json")),
                json.dumps([m.model_dump(mode="json") for m in result.mentioned_companies]),
                json.dumps([p.model_dump(mode="json") for p in result.perception_themes]),
                json.dumps([a.model_dump(mode="json") for a in result.articulated_blockers]),
                transcript.full_transcript or "",
                transcript.enhanced_notes or "",
                transcript.my_notes or "",
                "\n".join(n.text for n in (transcript.notes or []) if n.text),
            ]
        ).lower()

        for span in original_spans:
            needle = (span or "").strip().lower()
            if needle and needle in haystack:
                raise Article9RedactionError(
                    f"Article 9 redaction incomplete for meeting "
                    f"{result.meeting_id}: a detected special-category span "
                    f"survived the scrub and would be persisted. Refusing to "
                    f"write (fail closed). Span preview: {needle[:24]!r}…"
                )

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
    # Structured-comp plausibility flag (deterministic, code-side)
    # ---------------------------------------------------------------------
    @staticmethod
    def _flag_comp_plausibility(
        extraction: TalentStructuredExtraction,
    ) -> TalentStructuredExtraction:
        """
        Set `plausible` on each CompStructured the model emitted. The LLM is told
        NOT to self-assess plausibility; we decide deterministically so a garbled
        figure can be excluded from aggregate stats with a consistent rule.

        Per-period sane ranges (see `_comp_bounds`):
          - day:  ~£50–£5,000      (catches an ASR "$4.50" day rate)
          - hour: ~£5–£500         (catches an ASR "$1.25/hour")
          - year: ~£10,000–£2,000,000

        Rules:
          - No amount at all (amount_min and amount_max both None) → plausible=None
            (unknown, not flagged false — we have nothing to judge).
          - period not in the bounded set (None / "other") → plausible=None
            (no band to test against; don't assert false on an un-unitable figure).
          - Otherwise plausible iff EVERY present bound sits within the band.
            A range is implausible if either end falls outside.
        """
        bounds = _comp_bounds()

        def flag(comp: Optional[CompStructured]) -> None:
            if comp is None:
                return
            amounts = [a for a in (comp.amount_min, comp.amount_max) if a is not None]
            if not amounts or comp.period not in bounds:
                comp.plausible = None
                return
            lo, hi = bounds[comp.period]
            comp.plausible = all(lo <= a <= hi for a in amounts)

        flag(extraction.talent_market.current_comp_structured)
        flag(extraction.talent_market.expected_comp_structured)
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
