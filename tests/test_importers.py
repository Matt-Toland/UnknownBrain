import pytest
import tempfile
from pathlib import Path
from datetime import date

from src.importers.markdown import MarkdownImporter
from src.importers.plaintext import PlaintextImporter
from src.importers.html import HtmlImporter
from src.importers.zapier_granola import ZapierGranolaImporter
from src.schemas import Transcript


class TestMarkdownImporter:
    def setup_method(self):
        self.importer = MarkdownImporter()
    
    def test_parse_markdown_with_timestamps(self):
        content = """# TechCorp — Weekly Sync (2025-09-03)
Participants: John Doe (CEO); Jane Smith (CTO)
---
[00:01:30] John: We need to hire 5 engineers this quarter.
[00:05:00] Jane: Main blocker is budget approval.
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            
            transcript = self.importer.parse_file(Path(f.name))
            
            assert transcript.company == "TechCorp"
            assert transcript.date == date(2025, 9, 3)
            assert len(transcript.participants) == 2
            assert "John Doe (CEO)" in transcript.participants
            assert len(transcript.notes) == 2
            assert transcript.notes[0].t == "00:01:30"
            assert transcript.notes[0].speaker == "John"
            assert "hire 5 engineers" in transcript.notes[0].text
            
        Path(f.name).unlink()
    
    def test_parse_markdown_no_timestamps(self):
        content = """# StartupCo — Planning Session (2025-08-30)
Participants: Alice Brown (Founder)
---
Alice: Looking to expand team next year.
We'll need help with org design.
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            
            transcript = self.importer.parse_file(Path(f.name))
            
            assert transcript.company == "StartupCo"
            assert len(transcript.notes) >= 1
            assert transcript.notes[0].t is None
            assert transcript.notes[0].speaker == "Alice"
            
        Path(f.name).unlink()


class TestPlaintextImporter:
    def setup_method(self):
        self.importer = PlaintextImporter()
    
    def test_parse_plaintext_basic(self):
        content = """DataCorp - Strategy Meeting
2025-09-02
Participants: Mike Johnson (CTO), Sarah Wilson (VP Eng)

---

[00:02:15] Mike: We're hiring 10 engineers this quarter.
Sarah: What's the timeline?
[00:05:30] Mike: Need to fill roles by December.
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            f.flush()
            
            transcript = self.importer.parse_file(Path(f.name))
            
            assert transcript.company == "DataCorp"
            assert transcript.date == date(2025, 9, 2)
            assert len(transcript.participants) == 2
            assert len(transcript.notes) >= 2
            
        Path(f.name).unlink()


class TestHtmlImporter:
    def setup_method(self):
        self.importer = HtmlImporter()
    
    def test_parse_html_basic(self):
        content = """<!DOCTYPE html>
<html>
<head><title>WebCorp - Team Meeting</title></head>
<body>
    <h1>WebCorp — Team Meeting (2025-09-01)</h1>
    <p><strong>Participants:</strong> Tom Davis (CEO), Lisa Chen (CTO)</p>
    <div class="meeting-notes">
        <p><strong>[00:01:00] Tom:</strong> We need 3 senior developers urgently.</p>
        <p><strong>Lisa:</strong> Main blocker is salary budget.</p>
    </div>
</body>
</html>"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            f.write(content)
            f.flush()
            
            transcript = self.importer.parse_file(Path(f.name))
            
            assert transcript.company == "WebCorp"
            assert transcript.date == date(2025, 9, 1)
            assert len(transcript.notes) >= 1
            
        Path(f.name).unlink()


class TestZapierGranolaImporter:
    def setup_method(self):
        self.importer = ZapierGranolaImporter()
    
    def test_parse_zapier_payload(self):
        payload = {
            "id": "test-123",
            "company": "TestCorp",
            "date": "2025-09-03",
            "participants": "Alex Kim (CEO); Jordan Lee (CTO)",
            "content": "# Meeting Notes\n[00:01:00] Alex: We're hiring 5 people this month.\n[00:03:00] Jordan: Budget is approved."
        }
        
        transcript = self.importer.parse_zapier_payload(payload)
        
        assert transcript.company == "TestCorp"
        assert transcript.date == date(2025, 9, 3)
        assert len(transcript.participants) == 2
        assert len(transcript.notes) >= 2
        assert transcript.source == "zapier-granola"
    
    def test_parse_zapier_fixture_file(self):
        fixture_data = {
            "id": "fixture-456",
            "title": "FixtureCorp — Planning Meeting",
            "date": "2025-08-30T10:00:00Z",
            "content": "We're planning to hire next quarter after funding."
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            json.dump(fixture_data, f)
            f.flush()
            
            transcript = self.importer.parse_fixture_file(Path(f.name))
            
            assert transcript.meeting_id.startswith("fixture-456") or transcript.meeting_id.startswith("zap-")
            assert transcript.date == date(2025, 8, 30)
            
        Path(f.name).unlink()
    
    def test_field_mapping_tolerance(self):
        payload = {
            "note_id": "mapping-test",
            "organization": "MappingCorp", 
            "created_at": "2025-09-01T15:30:00Z",
            "attendees": "Pat Wilson, Sam Chen",
            "body": "Test content for mapping"
        }
        
        transcript = self.importer.parse_zapier_payload(payload)
        
        assert transcript.meeting_id == "mapping-test"
        assert transcript.company == "MappingCorp"
        assert transcript.date == date(2025, 9, 1)
        assert len(transcript.participants) == 2