"""
Pydantic schemas for the TalentScorer.

The vocabulary is constrained by Literal types so the LLM's structured output
either lands in the agreed taxonomy or fails loudly via Pydantic validation.
That's the point: we'd rather a scoring run fail than silently mis-categorise
a candidate or burn a row of analytics on a hallucinated label.

Six talent buckets (finalised with Carrie) plus three per-client intelligence
extensions (Ollie's late additions). Schema names map 1:1 onto BigQuery
column names in `meeting_intel`.

`current_employer_hiring_signal` lives on TalentNow only — it's a fact about
where the candidate is now, not a lead. Don't duplicate it on TalentLeads.
"""

from datetime import date as Date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Bucket 1 — Now: who the candidate is and where they sit today
# ---------------------------------------------------------------------------
TalentEmploymentStatus = Literal["employed", "between_roles", "on_leave"]


class TalentNow(BaseModel):
    role: Optional[str] = Field(None, description="Current job title")
    seniority: Optional[str] = Field(None, description="Seniority level (e.g. mid, senior, head of, director)")
    company_type: Optional[str] = Field(None, description="Type of company they work at (agency, in-house, consultancy, etc.)")
    company_lifecycle: Optional[str] = Field(None, description="Lifecycle stage (startup, scaleup, enterprise)")
    company_discipline: Optional[str] = Field(None, description="Primary discipline of the company")
    company_industry: Optional[str] = Field(None, description="Industry vertical")
    current_employer_hiring_signal: Optional[bool] = Field(
        None,
        description="Whether the candidate's current employer is hiring (BD lead signal)",
    )
    employment_status: Optional[TalentEmploymentStatus] = Field(
        None,
        description="Whether the candidate is currently employed, between roles, or on planned leave",
    )


# ---------------------------------------------------------------------------
# Bucket 3 — Motivation: what 'better' looks like for them
# ---------------------------------------------------------------------------
TalentMotivationDriver = Literal[
    "progression",
    "salary",
    "the_work",
    "flexibility",
    "work_life_balance",
    "company_type_change",
    "employment_type_change",
    "benefits",
    "location",
    "leadership",
    "remote_work",
]

TalentEmploymentPreference = Literal["permanent", "freelance", "contract", "open"]


class TalentMotivation(BaseModel):
    primary_driver: TalentMotivationDriver = Field(
        ..., description="The single biggest reason they're open to moving"
    )
    better_description: str = Field(
        ..., description="One-line description of what 'better' looks like for them"
    )
    employment_preference: Optional[TalentEmploymentPreference] = Field(
        None,
        description="Permanent / freelance / contract / open. Null if not articulated.",
    )


# ---------------------------------------------------------------------------
# Bucket 4 — Market reality: comp, notice, openness
# ---------------------------------------------------------------------------
CompCurrency = Literal["GBP", "USD", "EUR", "other"]
CompPeriod = Literal["day", "hour", "year", "other"]


class CompStructured(BaseModel):
    """
    Structured form of a free-text comp string, for aggregate statistics
    (salary-trend reporting by role/type), NOT recruiter filtering.

    The LLM emits everything EXCEPT `plausible` — that is computed
    deterministically in code (TalentScorer._flag_comp_plausibility) so a
    garbled figure (ASR decimal-place error like "$4.50/day") can be excluded
    from aggregates without relying on the model to self-assess.
    """
    currency: Optional[CompCurrency] = Field(
        None, description="Currency of the figure; infer from symbol/context where possible"
    )
    amount_min: Optional[float] = Field(
        None, description="Lower bound in the stated unit; equals amount_max for a single value"
    )
    amount_max: Optional[float] = Field(
        None, description="Upper bound in the stated unit; equals amount_min for a single value"
    )
    period: Optional[CompPeriod] = Field(
        None, description="Unit the amount is expressed in: per day, per hour, per year"
    )
    basis: Optional[str] = Field(
        None,
        description="What the figure covers: 'base' / 'base+bonus' / 'total' / 'equity-heavy' etc.",
    )
    plausible: Optional[bool] = Field(
        None,
        description="COMPUTED IN CODE — do not set. Whether the amount is in a sane range for its period.",
    )


class TalentMarket(BaseModel):
    current_comp: Optional[str] = Field(None, description="Current compensation (base + bonus + equity, free-text)")
    expected_comp: Optional[str] = Field(None, description="Expected compensation in next role")
    current_comp_structured: Optional[CompStructured] = Field(
        None, description="Structured form of current_comp (LLM-emitted; `plausible` set in code)"
    )
    expected_comp_structured: Optional[CompStructured] = Field(
        None, description="Structured form of expected_comp (LLM-emitted; `plausible` set in code)"
    )
    notice_period: Optional[str] = Field(None, description="Notice period at current employer")
    openness_to_move: Optional[int] = Field(
        None, ge=1, le=5, description="1=not looking, 5=actively interviewing"
    )
    realistic_time_to_move: Optional[str] = Field(
        None, description="How long until they could realistically start a new role"
    )


# ---------------------------------------------------------------------------
# Bucket 5 — Leads: BD funnel signal (companies they name-drop)
# ---------------------------------------------------------------------------
class TalentLeads(BaseModel):
    companies_mentioned: List[str] = Field(
        default_factory=list,
        description="Companies the candidate mentioned (current/former employers, targets, competitors)",
    )


# ---------------------------------------------------------------------------
# Per-client intelligence extensions (Ollie's late additions)
# ---------------------------------------------------------------------------
MentionedCompanyType = Literal["client", "competitor", "in_house", "independent", "other"]
MentionedCompanySentiment = Literal["positive", "negative", "neutral", "mixed"]
PerceptionSource = Literal["candidate", "recruiter"]


class MentionedCompany(BaseModel):
    name: str = Field(..., description="Company name (canonicalised via client_mappings if matched)")
    type: MentionedCompanyType
    sentiment: MentionedCompanySentiment
    evidence_quote: str = Field(..., description="Verbatim quote from the transcript")
    source: PerceptionSource = Field(
        ...,
        description="Whether the mention/perception came from the candidate or the recruiter",
    )


PerceptionTheme_T = Literal[
    "brand", "leadership", "comp", "culture", "scope", "ambition", "flexibility", "stability"
]
PerceptionTheme_Polarity = Literal["praise", "concern", "neutral"]


class PerceptionTheme(BaseModel):
    company_name: str = Field(..., description="Company being talked about (canonicalised)")
    theme: PerceptionTheme_T
    polarity: PerceptionTheme_Polarity
    evidence_quote: str = Field(..., description="Verbatim quote from the transcript")
    source: PerceptionSource = Field(
        ...,
        description="Whether the perception came from the candidate or the recruiter",
    )


ArticulatedBlockerCategory = Literal[
    "comp_gap", "brand", "scope", "leadership", "stability", "flexibility", "other"
]


class ArticulatedBlocker(BaseModel):
    # Optional since Brief 4 review: role/discipline/category/condition-shaped
    # blockers ("I don't want to be a middle person", "I won't do web design",
    # "I'm done with classic advertising agencies", "I can't work UK hours")
    # legitimately have no named company. The baseline test showed the LLM
    # inventing non-company strings ("general_contracting", "advertising
    # agencies") to satisfy a required field — worse than null.
    company_name: Optional[str] = Field(
        None,
        description="Company the blocker is about (canonicalised). Null for role/discipline/category/condition-shaped blockers.",
    )
    category: ArticulatedBlockerCategory
    evidence_quote: str = Field(..., description="Verbatim quote from the transcript")


# ---------------------------------------------------------------------------
# Article 9 — special-category data handling (UK GDPR Art. 9)
# ---------------------------------------------------------------------------
# The nine special categories. Detected during a dedicated pre-scoring pass on
# the ORIGINAL transcript text (talent domain only). Either flagged as metadata
# (default) or scrubbed at the front door before scoring (redact mode) so the
# scored fields are clean by construction. See TalentScorer for the write-gate.
Article9Category = Literal[
    "racial_or_ethnic_origin",
    "political_opinions",
    "religious_or_philosophical_beliefs",
    "trade_union_membership",
    "genetic_data",
    "biometric_data",
    "health",
    "sex_life",
    "sexual_orientation",
]

# Did the front-door scrub confirm the span was removed from the raw text?
# `confirmed` — span located and replaced. `partial` — span detected but could
# not be anchored in the raw phrasing to remove (must be visible, never silently
# assumed clean). Only meaningful in redact mode; None in flag mode.
Article9RawScrubStatus = Literal["confirmed", "partial"]


class Article9Flag(BaseModel):
    """
    One special-category reference detected in a talent transcript.

    `category`, `span`, `location`, `confidence` are LLM-emitted by the
    detection pass. `redacted` and `raw_scrub` are COMPUTED IN CODE (the LLM is
    told not to set them) — mirroring the comp `plausible` pattern. In redact
    mode the verbatim `span` is dropped (set None) before persistence so the
    special-category text itself is never stored; the metadata (category +
    location + redacted) still records that it was present and where.
    """
    category: Article9Category = Field(..., description="Which Article 9 special category")
    span: Optional[str] = Field(
        None,
        description="Verbatim span referencing the category. Dropped (None) once redacted.",
    )
    location: str = Field(
        ...,
        description="Where it appeared in the source (e.g. 'full_transcript', 'enhanced_notes', or a short locator).",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Detector confidence 0–1"
    )
    redacted: bool = Field(
        False, description="COMPUTED IN CODE — do not set. True once the span was scrubbed before persistence."
    )
    raw_scrub: Optional[Article9RawScrubStatus] = Field(
        None,
        description="COMPUTED IN CODE — do not set. 'confirmed'/'partial' scrub outcome (redact mode only).",
    )


class Article9Detection(BaseModel):
    """Response shape for the dedicated Article 9 detection pass."""
    flags: List[Article9Flag] = Field(
        default_factory=list,
        description="Every Article 9 special-category reference found in the transcript (empty if none).",
    )


# ---------------------------------------------------------------------------
# Pass 1 response schema — everything the structured-extraction call returns
# ---------------------------------------------------------------------------
class TalentStructuredExtraction(BaseModel):
    """
    Exact shape requested from the OpenAI structured-output call in Pass 1.
    Narrative is generated in a second pass (Pass 2) using this as context.
    """
    talent_now: TalentNow
    talent_triggers: List[str] = Field(
        default_factory=list,
        description="Top reasons for being open to moving (1-3 short phrases)",
    )
    talent_motivation: TalentMotivation
    talent_market: TalentMarket
    talent_leads: TalentLeads
    mentioned_companies: List[MentionedCompany] = Field(default_factory=list)
    perception_themes: List[PerceptionTheme] = Field(default_factory=list)
    articulated_blockers: List[ArticulatedBlocker] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level result returned by TalentScorer.score_transcript_new()
# ---------------------------------------------------------------------------
class TalentScoringResult(BaseModel):
    """
    Final result combining Pass 1 structured extraction + Pass 2 narrative.

    Flat shape (not nested) so the BQ write-path can read each field directly.
    Mirrors NewScoreResult's structure for consistency with the client path.
    """
    meeting_id: str
    date: Date

    # Pass 1 — structured extraction
    talent_now: TalentNow
    talent_triggers: List[str] = Field(default_factory=list)
    talent_motivation: TalentMotivation
    talent_market: TalentMarket
    talent_leads: TalentLeads
    mentioned_companies: List[MentionedCompany] = Field(default_factory=list)
    perception_themes: List[PerceptionTheme] = Field(default_factory=list)
    articulated_blockers: List[ArticulatedBlocker] = Field(default_factory=list)

    # Pass 2 — narrative prose
    talent_narrative: str

    # Article 9 special-category handling metadata (talent only). Always
    # populated by the detection pass; in redact mode each flag's verbatim
    # `span` is dropped and `redacted=True`.
    article9_flags: List[Article9Flag] = Field(default_factory=list)

    # Processing metadata
    scored_at: datetime
    llm_model: str
