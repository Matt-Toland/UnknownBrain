import pytest
from datetime import date
from src.schemas import Transcript, Note
from src.rules import ScoringRules
from src.scoring import TranscriptScorer


class TestScoringRules:
    def setup_method(self):
        self.rules = ScoringRules()
    
    def test_check_now_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="We need to hire 3 engineers this month ASAP."),
            Note(t="00:02:00", speaker="Bob", text="Other discussion point.")
        ]
        
        result = self.rules.check_now(notes)
        
        assert result.score == 1
        assert result.evidence_line == "We need to hire 3 engineers this month ASAP."
        assert result.timestamp == "00:01:00"
    
    def test_check_now_negative(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="Just general discussion about the market."),
            Note(t="00:02:00", speaker="Bob", text="No urgent hiring mentioned.")
        ]
        
        result = self.rules.check_now(notes)
        
        assert result.score == 0
        assert result.evidence_line is None
    
    def test_check_next_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="We plan to hire next quarter after funding round."),
            Note(t="00:02:00", speaker="Bob", text="Other topic.")
        ]
        
        result = self.rules.check_next(notes)
        
        assert result.score == 1
        assert result.evidence_line == "We plan to hire next quarter after funding round."
    
    def test_check_measure_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="Our time-to-hire target is 30 days."),
            Note(t="00:02:00", speaker="Bob", text="Offer acceptance rate should be above 85%.")
        ]
        
        result = self.rules.check_measure(notes)
        
        assert result.score == 1
        assert "time-to-hire" in result.evidence_line
    
    def test_check_blocker_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="Main blocker is budget approval delay."),
            Note(t="00:02:00", speaker="Bob", text="We're also blocked by skills shortage.")
        ]
        
        result = self.rules.check_blocker(notes)
        
        assert result.score == 1
        assert "blocker" in result.evidence_line.lower()
    
    def test_check_fit_talent_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="We need help with recruiting and sourcing candidates."),
            Note(t="00:02:00", speaker="Bob", text="Our interview process needs optimization.")
        ]
        
        result = self.rules.check_fit(notes)
        
        assert result.score == 1
        assert "Talent" in result.fit_labels
    
    def test_check_fit_evolve_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="Need help with org design and salary bands."),
            Note(t="00:02:00", speaker="Bob", text="Performance management system needs overhaul.")
        ]
        
        result = self.rules.check_fit(notes)
        
        assert result.score == 1
        assert "Evolve" in result.fit_labels
    
    def test_check_fit_ventures_positive(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="We're launching a pilot program for new market."),
            Note(t="00:02:00", speaker="Bob", text="Need help with MVP development and experiments.")
        ]
        
        result = self.rules.check_fit(notes)
        
        assert result.score == 1
        assert "Ventures" in result.fit_labels
    
    def test_check_fit_multiple_labels(self):
        notes = [
            Note(t="00:01:00", speaker="Alice", text="Need recruiting help and org design support."),
            Note(t="00:02:00", speaker="Bob", text="Also launching pilot in new market segment.")
        ]
        
        result = self.rules.check_fit(notes)
        
        assert result.score == 1
        assert len(result.fit_labels) >= 2
        assert "Talent" in result.fit_labels
        assert "Evolve" in result.fit_labels


class TestTranscriptScorer:
    def setup_method(self):
        self.scorer = TranscriptScorer()
    
    def test_score_transcript_high_score(self):
        transcript = Transcript(
            meeting_id="high-score-test",
            date=date(2025, 9, 3),
            company="TestCorp",
            participants=["Alice (CEO)", "Bob (CTO)"],
            notes=[
                Note(t="00:01:00", speaker="Alice", text="We need to hire 5 engineers this quarter ASAP."),
                Note(t="00:02:00", speaker="Bob", text="After that, we plan to expand next quarter too."),
                Note(t="00:03:00", speaker="Alice", text="Our time-to-hire target is 30 days maximum."),
                Note(t="00:04:00", speaker="Bob", text="Main blocker is budget approval from board."),
                Note(t="00:05:00", speaker="Alice", text="Need help with recruiting and interview processes.")
            ],
            source="test"
        )
        
        result = self.scorer.score_transcript(transcript)
        
        assert result.total_score == 5
        assert result.qualified == True
        assert result.checks['now']['score'] == 1
        assert result.checks['next']['score'] == 1
        assert result.checks['measure']['score'] == 1
        assert result.checks['blocker']['score'] == 1
        assert result.checks['fit']['score'] == 1
    
    def test_score_transcript_low_score(self):
        transcript = Transcript(
            meeting_id="low-score-test",
            date=date(2025, 9, 3),
            company="TestCorp",
            participants=["Alice (CEO)"],
            notes=[
                Note(t="00:01:00", speaker="Alice", text="Just general discussion about market trends."),
                Note(t="00:02:00", speaker="Alice", text="No specific hiring plans at the moment.")
            ],
            source="test"
        )
        
        result = self.scorer.score_transcript(transcript)
        
        assert result.total_score <= 2
        assert result.qualified == False
    
    def test_score_transcript_qualified_threshold(self):
        transcript = Transcript(
            meeting_id="threshold-test",
            date=date(2025, 9, 3),
            company="TestCorp",
            participants=["Alice (CEO)"],
            notes=[
                Note(t="00:01:00", speaker="Alice", text="We're hiring this month urgently."),
                Note(t="00:02:00", speaker="Alice", text="Time-to-hire should be under 45 days."),
                Note(t="00:03:00", speaker="Alice", text="Need recruiting support for these roles.")
            ],
            source="test"
        )
        
        result = self.scorer.score_transcript(transcript)
        
        assert result.total_score >= 3
        assert result.qualified == True