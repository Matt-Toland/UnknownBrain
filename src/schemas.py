from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date as Date, datetime
import os


class Note(BaseModel):
    t: Optional[str] = Field(None, description="Timestamp in format HH:MM:SS or MM:SS")
    speaker: Optional[str] = Field(None, description="Speaker name")
    text: str = Field(..., description="Content of the note")


class Transcript(BaseModel):
    meeting_id: str = Field(..., description="Unique meeting identifier")
    date: Date = Field(..., description="Meeting date")
    company: Optional[str] = Field(None, description="Company name")
    participants: List[str] = Field(default_factory=list, description="List of participants")
    desk: str = Field(default="Unknown", description="Business category")
    notes: List[Note] = Field(default_factory=list, description="Meeting notes")
    source: str = Field(..., description="Source of the transcript (e.g., dummy-md, zapier)")
    
    # Granola metadata fields
    granola_note_id: Optional[str] = Field(None, description="Granola note unique identifier")
    title: Optional[str] = Field(None, description="Meeting title from Granola")
    creator_name: Optional[str] = Field(None, description="Meeting creator name")
    creator_email: Optional[str] = Field(None, description="Creator email address")
    calendar_event_title: Optional[str] = Field(None, description="Calendar event title")
    calendar_event_id: Optional[str] = Field(None, description="Calendar event ID")
    calendar_event_time: Optional[str] = Field(None, description="Calendar event timestamp")
    granola_link: Optional[str] = Field(None, description="Link to Granola note")
    file_created_timestamp: Optional[str] = Field(None, description="File creation timestamp")
    zapier_step_id: Optional[str] = Field(None, description="Zapier automation step ID")
    
    # Content sections for BigQuery
    enhanced_notes: Optional[str] = Field(None, description="Full Enhanced Notes section")
    my_notes: Optional[str] = Field(None, description="Full My Notes section")
    full_transcript: Optional[str] = Field(None, description="Full transcript section")


class SectionResult(BaseModel):
    """Compact scoring result for individual sections (NOW, NEXT, MEASURE, BLOCKER)"""
    qualified: bool = Field(..., description="True if section criteria met")
    reason: str = Field(..., description="Short explanation for the decision")
    summary: str = Field(..., description="1-3 sentences; include numbers/timeframes only if stated; else 'Not stated.'")
    evidence: Optional[str] = Field(None, description="Verbatim quote ≤25 words or null")


class FitResult(BaseModel):
    """Enhanced FIT scoring with multiple service categories"""
    qualified: bool = Field(..., description="True if any fit found")
    reason: str = Field(..., description="Short explanation for the decision")
    summary: str = Field(..., description="1-3 sentences; include numbers/timeframes only if stated; else 'Not stated.'")
    services: List[str] = Field(default_factory=list, description="Matching UNKNOWN services (talent, evolve, ventures)")
    evidence: Optional[str] = Field(None, description="Verbatim quote ≤25 words or null")


class SalesAssessmentResult(BaseModel):
    """
    Scoring result for individual salesperson assessment criteria.

    Unlike SectionResult which analyzes client statements ("Them:"),
    this analyzes the UNKNOWN rep's behavior ("Me:" speakers).
    """
    qualified: bool = Field(..., description="True if salesperson demonstrated this behavior adequately")
    score: int = Field(..., ge=0, le=3, description="0=Not done, 1=Weak, 2=Adequate, 3=Strong")
    reason: str = Field(..., description="Short explanation for the score")
    evidence: Optional[str] = Field(None, description="Verbatim quote from 'Me:' speaker demonstrating behavior")
    coaching_note: Optional[str] = Field(None, description="Specific improvement suggestion for this criterion")


class SalesScoreResult(BaseModel):
    """
    Complete salesperson assessment result with all 8 criteria.

    Criteria based on Carrie's feedback:
    1. Introduction & Framing
    2. Discovery (problems/pain points)
    3. Opportunity Scoping (budgets, volumes, process)
    4. Solution Positioning (matching to UNKNOWN products)
    5. Commercial Confidence (fees discussion)
    6. Case Studies (sharing proof)
    7. Next Steps & Stakeholders (closing the meeting)
    8. Strategic Context (now/future/blockers)
    """
    meeting_id: str = Field(..., description="Meeting identifier")
    salesperson_name: Optional[str] = Field(None, description="Name of the UNKNOWN rep being assessed")
    salesperson_email: Optional[str] = Field(None, description="Email of the UNKNOWN rep")
    date: Date = Field(..., description="Meeting date")
    client: Optional[str] = Field(None, description="Client company name")

    # Total scores
    total_score: int = Field(..., ge=0, le=24, description="Total score (0-24, sum of 8 criteria x 0-3 each)")
    total_qualified: int = Field(..., ge=0, le=8, description="Number of criteria qualified (0-8)")

    # Individual assessment criteria (JSON blobs)
    introduction: SalesAssessmentResult = Field(..., description="Introduction & Framing assessment")
    discovery: SalesAssessmentResult = Field(..., description="Discovery of problems/pain assessment")
    scoping: SalesAssessmentResult = Field(..., description="Opportunity scoping assessment")
    solution: SalesAssessmentResult = Field(..., description="Solution positioning assessment")
    commercial: SalesAssessmentResult = Field(..., description="Commercial confidence assessment")
    case_studies: SalesAssessmentResult = Field(..., description="Case studies/proof points assessment")
    next_steps: SalesAssessmentResult = Field(..., description="Next steps & stakeholder mapping assessment")
    strategic_context: SalesAssessmentResult = Field(..., description="Strategic context gathering assessment")

    # Overall coaching summary
    strengths: List[str] = Field(default_factory=list, description="Top 2-3 things done well")
    improvements: List[str] = Field(default_factory=list, description="Top 2-3 areas to improve")
    overall_coaching: Optional[str] = Field(None, description="Overall coaching note for this meeting")

    # Processing metadata
    scored_at: datetime = Field(..., description="When scoring was performed")
    llm_model: str = Field(..., description="LLM model used for scoring")

    @property
    def qualified(self) -> bool:
        """Returns True if salesperson met threshold (default: 5/8 criteria)"""
        threshold = int(os.getenv('SALES_QUALIFICATION_THRESHOLD', '5'))
        return self.total_qualified >= threshold

    @property
    def performance_rating(self) -> str:
        """Returns performance tier based on total score"""
        if self.total_score >= 20:
            return "Excellent"
        elif self.total_score >= 16:
            return "Good"
        elif self.total_score >= 12:
            return "Developing"
        else:
            return "Needs Improvement"


class ClientInfo(BaseModel):
    """Enhanced client information with multiple extraction sources"""
    client_id: Optional[str] = Field(None, description="Unique client identifier for future use")
    client: Optional[str] = Field(None, description="Primary client name")
    domain: Optional[str] = Field(None, description="Client domain (e.g., fintech, healthcare)")
    size: Optional[str] = Field(None, description="Company size category (startup, scaleup, enterprise)")
    source: str = Field(..., description="How client was identified (filename, llm, domain)")


class NewScoreResult(BaseModel):
    """Modern scoring result with JSON blob format and configurable thresholds"""
    meeting_id: str = Field(..., description="Meeting identifier")
    client_info: ClientInfo = Field(..., description="Enhanced client information")
    date: Date = Field(..., description="Meeting date")
    total_qualified_sections: int = Field(..., description="Total qualified sections (0-5)")

    # JSON blob scoring sections
    now: SectionResult = Field(..., description="NOW section scoring (JSON blob)")
    next: SectionResult = Field(..., description="NEXT section scoring (JSON blob)")
    measure: SectionResult = Field(..., description="MEASURE section scoring (JSON blob)")
    blocker: SectionResult = Field(..., description="BLOCKER section scoring (JSON blob)")
    fit: FitResult = Field(..., description="FIT section scoring (JSON blob)")

    # Client taxonomy tagging
    challenges: List[str] = Field(default_factory=list, description="Client challenges from taxonomy")
    results: List[str] = Field(default_factory=list, description="Desired results from taxonomy")
    offering: Optional[str] = Field(None, description="Primary offering type from taxonomy")

    # Processing metadata
    scored_at: datetime = Field(..., description="When scoring was performed")
    llm_model: str = Field(..., description="LLM model used for scoring")

    @property
    def qualified(self) -> bool:
        """Returns True if qualified sections meets configurable threshold"""
        threshold = int(os.getenv('QUALIFICATION_THRESHOLD', '3'))
        return self.total_qualified_sections >= threshold


# Legacy ScoreResult for backward compatibility
class ScoreResult(BaseModel):
    meeting_id: str = Field(..., description="Meeting identifier")
    company: Optional[str] = Field(None, description="Company name")
    date: Date = Field(..., description="Meeting date")
    total_qualified_sections: int = Field(..., description="Total qualified sections (0-5)")
    checks: Dict[str, Any] = Field(..., description="Individual check results")

    @property
    def qualified(self) -> bool:
        """Returns True if score >= 3/5"""
        return self.total_qualified_sections >= 3


class LeaderboardEntry(BaseModel):
    meeting_id: str
    company: Optional[str]
    date: Date
    total_qualified_sections: int
    qualified: bool
    fit_labels: List[str]


class NewScoredTranscript(BaseModel):
    """Modern transcript and scoring data for new meeting_intel BigQuery table"""

    # Core transcript fields
    meeting_id: str = Field(..., description="Unique meeting identifier")
    date: Date = Field(..., description="Meeting date")
    participants: List[str] = Field(default_factory=list, description="List of participants")
    desk: str = Field(default="Unknown", description="Business category")
    source: str = Field(..., description="Source of the transcript")

    # Enhanced client information
    client_info: Dict[str, Any] = Field(..., description="Client information as JSON blob")

    # Granola metadata fields
    granola_note_id: Optional[str] = Field(None, description="Granola note unique identifier")
    title: Optional[str] = Field(None, description="Meeting title from Granola")
    creator_name: Optional[str] = Field(None, description="Meeting creator name")
    creator_email: Optional[str] = Field(None, description="Creator email address")
    calendar_event_title: Optional[str] = Field(None, description="Calendar event title")
    calendar_event_id: Optional[str] = Field(None, description="Calendar event ID")
    calendar_event_time: Optional[str] = Field(None, description="Calendar event timestamp")
    granola_link: Optional[str] = Field(None, description="Link to Granola note")
    file_created_timestamp: Optional[str] = Field(None, description="File creation timestamp")
    zapier_step_id: Optional[str] = Field(None, description="Zapier automation step ID")

    # Content sections
    enhanced_notes: Optional[str] = Field(None, description="Full Enhanced Notes section")
    my_notes: Optional[str] = Field(None, description="Full My Notes section")
    full_transcript: Optional[str] = Field(None, description="Full transcript section")

    # Scoring results
    total_qualified_sections: int = Field(..., description="Total qualified sections (0-5)")
    qualified: bool = Field(..., description="True if score meets threshold")

    # JSON blob scoring sections
    now: Dict[str, Any] = Field(..., description="NOW scoring as JSON blob")
    next: Dict[str, Any] = Field(..., description="NEXT scoring as JSON blob")
    measure: Dict[str, Any] = Field(..., description="MEASURE scoring as JSON blob")
    blocker: Dict[str, Any] = Field(..., description="BLOCKER scoring as JSON blob")
    fit: Dict[str, Any] = Field(..., description="FIT scoring as JSON blob")

    # Client taxonomy tagging
    challenges: List[str] = Field(default_factory=list, description="Client challenges from taxonomy")
    results: List[str] = Field(default_factory=list, description="Desired results from taxonomy")
    offering: Optional[str] = Field(None, description="Primary offering type from taxonomy")

    # Processing metadata
    scored_at: datetime = Field(..., description="When scoring was performed")
    llm_model: str = Field(..., description="LLM model used for scoring")

    # === Salesperson Assessment Fields ===

    # Salesperson identification
    salesperson_name: Optional[str] = Field(None, description="UNKNOWN rep name (from creator_name)")
    salesperson_email: Optional[str] = Field(None, description="UNKNOWN rep email (from creator_email)")

    # Sales assessment scores
    sales_total_score: int = Field(default=0, ge=0, le=24, description="Total sales assessment score (0-24)")
    sales_total_qualified: int = Field(default=0, ge=0, le=8, description="Number of sales criteria qualified (0-8)")
    sales_qualified: bool = Field(default=False, description="True if sales assessment meets threshold")

    # Sales assessment JSON blobs (8 criteria)
    sales_introduction: Optional[Dict[str, Any]] = Field(None, description="Introduction & Framing assessment (JSON)")
    sales_discovery: Optional[Dict[str, Any]] = Field(None, description="Discovery assessment (JSON)")
    sales_scoping: Optional[Dict[str, Any]] = Field(None, description="Opportunity scoping assessment (JSON)")
    sales_solution: Optional[Dict[str, Any]] = Field(None, description="Solution positioning assessment (JSON)")
    sales_commercial: Optional[Dict[str, Any]] = Field(None, description="Commercial confidence assessment (JSON)")
    sales_case_studies: Optional[Dict[str, Any]] = Field(None, description="Case studies assessment (JSON)")
    sales_next_steps: Optional[Dict[str, Any]] = Field(None, description="Next steps assessment (JSON)")
    sales_strategic_context: Optional[Dict[str, Any]] = Field(None, description="Strategic context assessment (JSON)")

    # Overall coaching
    sales_strengths: List[str] = Field(default_factory=list, description="Top strengths identified")
    sales_improvements: List[str] = Field(default_factory=list, description="Top improvement areas")
    sales_overall_coaching: Optional[str] = Field(None, description="Overall coaching note")


# Legacy ScoredTranscript for backward compatibility
class ScoredTranscript(BaseModel):
    """Legacy combined transcript and scoring data for BigQuery export"""

    # Core transcript fields
    meeting_id: str = Field(..., description="Unique meeting identifier")
    date: Date = Field(..., description="Meeting date")
    company: Optional[str] = Field(None, description="Company name")
    participants: List[str] = Field(default_factory=list, description="List of participants")
    desk: str = Field(default="Unknown", description="Business category")
    source: str = Field(..., description="Source of the transcript")

    # Granola metadata fields
    granola_note_id: Optional[str] = Field(None, description="Granola note unique identifier")
    title: Optional[str] = Field(None, description="Meeting title from Granola")
    creator_name: Optional[str] = Field(None, description="Meeting creator name")
    creator_email: Optional[str] = Field(None, description="Creator email address")
    calendar_event_title: Optional[str] = Field(None, description="Calendar event title")
    calendar_event_id: Optional[str] = Field(None, description="Calendar event ID")
    calendar_event_time: Optional[str] = Field(None, description="Calendar event timestamp")
    granola_link: Optional[str] = Field(None, description="Link to Granola note")
    file_created_timestamp: Optional[str] = Field(None, description="File creation timestamp")
    zapier_step_id: Optional[str] = Field(None, description="Zapier automation step ID")

    # Content sections
    enhanced_notes: Optional[str] = Field(None, description="Full Enhanced Notes section")
    my_notes: Optional[str] = Field(None, description="Full My Notes section")
    full_transcript: Optional[str] = Field(None, description="Full transcript section")

    # Scoring results
    total_qualified_sections: int = Field(..., description="Total qualified sections (0-5)")
    qualified: bool = Field(..., description="True if score >= 3")

    # Individual check results (flattened for BQ)
    now_score: int = Field(..., description="NOW check score (0 or 1)")
    now_evidence: Optional[str] = Field(None, description="NOW check evidence")
    now_timestamp: Optional[str] = Field(None, description="NOW check timestamp")

    next_score: int = Field(..., description="NEXT check score (0 or 1)")
    next_evidence: Optional[str] = Field(None, description="NEXT check evidence")
    next_timestamp: Optional[str] = Field(None, description="NEXT check timestamp")

    measure_score: int = Field(..., description="MEASURE check score (0 or 1)")
    measure_evidence: Optional[str] = Field(None, description="MEASURE check evidence")
    measure_timestamp: Optional[str] = Field(None, description="MEASURE check timestamp")

    blocker_score: int = Field(..., description="BLOCKER check score (0 or 1)")
    blocker_evidence: Optional[str] = Field(None, description="BLOCKER check evidence")
    blocker_timestamp: Optional[str] = Field(None, description="BLOCKER check timestamp")

    fit_score: int = Field(..., description="FIT check score (0 or 1)")
    fit_labels: List[str] = Field(default_factory=list, description="FIT categories")
    fit_evidence: Optional[str] = Field(None, description="FIT check evidence")
    fit_timestamp: Optional[str] = Field(None, description="FIT check timestamp")

    # Processing metadata
    scored_at: datetime = Field(..., description="When scoring was performed")
    llm_model: str = Field(..., description="LLM model used for scoring")


# =============================================================================
# SALESPERSON ASSESSMENT CRITERIA (for LLM prompts)
# =============================================================================

SALES_ASSESSMENT_CRITERIA = {
    "introduction": {
        "name": "Introduction & Framing",
        "description": "Are they confidently setting the tone of the meeting?",
        "qualified_when": [
            "Introduced themselves and UNKNOWN succinctly",
            "Framed the purpose of the meeting",
            "Set an agenda (discovery → solutions → next steps)",
            "Asked permission to ask probing/challenging questions"
        ],
        "scoring": {
            0: "No introduction or framing attempted",
            1: "Basic intro but no agenda or framing",
            2: "Good intro with some agenda setting",
            3: "Strong intro with clear agenda, permission to probe, and meeting control"
        }
    },
    "discovery": {
        "name": "Discovery of Problems & Pain",
        "description": "Are they uncovering the stuff that actually makes clients buy?",
        "qualified_when": [
            "Uncovered high-level business challenges",
            "Identified specific talent/hiring challenges",
            "Explored impact of challenges (cost, time, burnout, quality, opportunity loss)",
            "Identified emotional drivers (frustration, urgency, risk, ambition)",
            "Asked what they've tried before and what didn't work",
            "Asked layered, high-quality questions (peeled the onion)"
        ],
        "scoring": {
            0: "No meaningful discovery questions asked",
            1: "Surface-level questions only",
            2: "Good discovery with some depth",
            3: "Excellent layered discovery uncovering business impact and emotional drivers"
        }
    },
    "scoping": {
        "name": "Opportunity Scoping & Qualification",
        "description": "Are they properly qualifying the opportunity?",
        "qualified_when": [
            "Discussed budgets (perm, freelance, project, embedded)",
            "Forecast hiring volumes (3-6-12 months)",
            "Understood current hiring operating model",
            "Defined what 'good' looks like for them",
            "Identified stakeholders involved",
            "Understood buying process and timeline",
            "Asked about competing priorities"
        ],
        "scoring": {
            0: "No scoping or qualification attempted",
            1: "Basic scoping (1-2 elements)",
            2: "Good scoping covering budget and timeline",
            3: "Comprehensive scoping with budget, volumes, stakeholders, and process"
        }
    },
    "solution": {
        "name": "Positioning UNKNOWN & Productising the Solution",
        "description": "Are they positioning, not just pitching?",
        "qualified_when": [
            "Matched client problems to UNKNOWN products (Partnership, Bench, Search, Ventures)",
            "Told relevant stories/case studies",
            "Used business outcomes, not features",
            "Elevated UNKNOWN as advisors vs. recruiters"
        ],
        "scoring": {
            0: "No solution positioning attempted",
            1: "Generic pitch without matching to client needs",
            2: "Good positioning with some product matching",
            3: "Strong positioning with clear problem-to-product mapping and outcome focus"
        }
    },
    "commercial": {
        "name": "Commercial Confidence",
        "description": "Are they comfortable and credible when talking money?",
        "qualified_when": [
            "Stated potential fees/proposal early, not apologetically",
            "Explained value behind fees (benchmarks, intelligence, risk reduction)",
            "Discussed payment structure (deposit, retainers)",
            "Handled pushback without discounting",
            "Checked budget alignment before sending proposal"
        ],
        "scoring": {
            0: "No commercial discussion or avoided the topic",
            1: "Mentioned fees but apologetically or vaguely",
            2: "Clear fee discussion with some value articulation",
            3: "Confident commercial discussion with value justification and budget alignment"
        }
    },
    "case_studies": {
        "name": "Case Studies & Proof Points",
        "description": "Are they sharing relevant proof of UNKNOWN's capability?",
        "qualified_when": [
            "Shared relevant case studies",
            "Used specific examples with outcomes",
            "Matched proof points to client's situation",
            "Demonstrated credibility through stories"
        ],
        "scoring": {
            0: "No case studies or proof points shared",
            1: "Generic or irrelevant examples",
            2: "Relevant case study but limited detail",
            3: "Strong, relevant case studies with specific outcomes matched to client needs"
        }
    },
    "next_steps": {
        "name": "Next Steps & Stakeholder Mapping",
        "description": "Do they land the plane?",
        "qualified_when": [
            "Confirmed the buying process",
            "Identified all decision-makers and influencers",
            "Agreed a clear next step with date/time",
            "Summarised what they heard and what comes next",
            "Confirmed what's needed from client (brief, data, org chart)",
            "Created momentum rather than leaving things open-ended"
        ],
        "scoring": {
            0: "No clear next steps agreed",
            1: "Vague next steps without dates or owners",
            2: "Clear next step but limited stakeholder mapping",
            3: "Strong close with clear next step, stakeholder map, and momentum created"
        }
    },
    "strategic_context": {
        "name": "Strategic Context Gathering",
        "description": "Are they future-proofing the partnership?",
        "qualified_when": [
            "Understood where the business is going (ambition, GTM, growth plans)",
            "Identified org design challenges / product roadmap / market conditions",
            "Uncovered talent bottlenecks blocking growth",
            "Defined what success looks like in 12 months",
            "Spotted cross-sell opportunities organically"
        ],
        "scoring": {
            0: "No strategic context gathered",
            1: "Basic understanding of current state only",
            2: "Good understanding of direction but limited depth",
            3: "Comprehensive strategic picture with future vision and cross-sell awareness"
        }
    }
}