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
    total_score: int
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

    # Processing metadata
    scored_at: datetime = Field(..., description="When scoring was performed")
    llm_model: str = Field(..., description="LLM model used for scoring")


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