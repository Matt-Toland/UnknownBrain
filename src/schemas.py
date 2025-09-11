from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date as Date, datetime


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


class CheckResult(BaseModel):
    score: int = Field(..., description="1 if check passed, 0 if failed")
    evidence_line: Optional[str] = Field(None, description="Evidence supporting the score")
    timestamp: Optional[str] = Field(None, description="Timestamp of evidence")


class FitResult(BaseModel):
    score: int = Field(..., description="1 if any fit found, 0 otherwise")
    fit_labels: List[str] = Field(default_factory=list, description="Matching fit categories")
    evidence_line: Optional[str] = Field(None, description="Evidence supporting the fit")
    timestamp: Optional[str] = Field(None, description="Timestamp of evidence")


class ScoreResult(BaseModel):
    meeting_id: str = Field(..., description="Meeting identifier")
    company: Optional[str] = Field(None, description="Company name")
    date: Date = Field(..., description="Meeting date")
    total_score: int = Field(..., description="Total score out of 5")
    checks: Dict[str, Any] = Field(..., description="Individual check results")
    
    @property
    def qualified(self) -> bool:
        """Returns True if score >= 3/5"""
        return self.total_score >= 3


class LeaderboardEntry(BaseModel):
    meeting_id: str
    company: Optional[str]
    date: Date
    total_score: int
    qualified: bool
    fit_labels: List[str]


class ScoredTranscript(BaseModel):
    """Combined transcript and scoring data for BigQuery export"""
    
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
    total_score: int = Field(..., description="Total score out of 5")
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