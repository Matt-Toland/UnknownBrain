import pytest
import tempfile
from pathlib import Path
from datetime import date

from src.importers.plaintext import PlaintextImporter
from src.importers.granola_drive import GranolaDriveImporter
from src.schemas import Transcript


class TestPlaintextImporter:
    def setup_method(self):
        self.importer = PlaintextImporter()

    def test_parse_plaintext_with_timestamps(self):
        content = """Meeting Notes - TechCorp Weekly Sync
Date: 2025-09-03
Participants: John Doe (CEO), Jane Smith (CTO)

[10:00] John: Let's start with the quarterly review
[10:05] Jane: The new AI system is performing well
[10:10] John: What are the main challenges?
[10:12] Jane: We need more senior engineers for the scaling effort
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()

            transcript = self.importer.parse_file(Path(f.name))

            assert isinstance(transcript, Transcript)
            assert len(transcript.notes) > 0
            assert transcript.source == 'plaintext'

            # Check that notes with timestamps are parsed correctly
            timestamped_notes = [note for note in transcript.notes if note.t is not None]
            assert len(timestamped_notes) >= 4

            # Verify speaker extraction
            speaker_notes = [note for note in transcript.notes if note.speaker is not None]
            assert len(speaker_notes) >= 4

            Path(f.name).unlink()


class TestGranolaDriveImporter:
    def setup_method(self):
        self.importer = GranolaDriveImporter()

    def test_parse_granola_file_with_json_metadata(self):
        content = '''```json
{
  "granola_note_id": "test-123",
  "title": "Test Meeting",
  "creator_name": "John Doe",
  "creator_email": "john@example.com",
  "calendar_event_time": "2025-09-03T10:00:00+00:00",
  "zapier_step_id": "456",
  "file_created_timestamp": "1693737600"
}
```

# Test Meeting

## Enhanced Notes
- Key discussion about product roadmap
- Need to hire 5 engineers in next quarter

## My Notes
- Follow up on budget approval
- Schedule next review meeting

## Full Transcript
John: Welcome everyone to the meeting
Jane: Thanks for joining, let's discuss the roadmap
'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            f.flush()

            transcript = self.importer.parse_file(Path(f.name))

            assert isinstance(transcript, Transcript)
            assert transcript.source == 'granola_drive'
            assert transcript.granola_note_id == 'test-123'
            assert transcript.title == 'Test Meeting'
            assert transcript.creator_name == 'John Doe'
            assert transcript.creator_email == 'john@example.com'
            assert transcript.zapier_step_id == '456'
            assert transcript.file_created_timestamp == '1693737600'

            # Check content sections
            assert 'product roadmap' in transcript.enhanced_notes
            assert 'budget approval' in transcript.my_notes
            assert 'Welcome everyone' in transcript.full_transcript

            # Verify notes were created from all sections
            assert len(transcript.notes) > 0

            Path(f.name).unlink()

    def test_parse_granola_file_with_malformed_json(self):
        content = '''```json
{
  "granola_note_id": "test-456",
  "title": "Malformed Test",
  "attendees": email: test@example.com
name: Test User,
  "calendar_event_time": "2025-09-03T10:00:00+00:00"
}
```

# Malformed Test

## Enhanced Notes
- This should still work despite malformed JSON
'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            f.flush()

            # Should not raise an exception
            transcript = self.importer.parse_file(Path(f.name))

            assert isinstance(transcript, Transcript)
            assert transcript.granola_note_id == 'test-456'
            assert transcript.title == 'Malformed Test'

            Path(f.name).unlink()