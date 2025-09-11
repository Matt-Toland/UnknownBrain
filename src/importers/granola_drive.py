import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

from ..schemas import Transcript, Note


class GranolaDriveImporter:
    def __init__(self):
        self.filename_pattern = re.compile(r'^\[([^\]]+)\]\s*(.+?)\s*-\s*(.+?)\s*-\s*(.+)\.txt$')
        
    def parse_file(self, file_path: Path) -> Transcript:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract JSON metadata from header
        metadata = self._extract_json_metadata(content)
        
        # Parse filename for fallback info
        creator, title, date_str = self._parse_filename(file_path.name)
        
        # Extract content sections
        enhanced_notes = self._extract_enhanced_notes(content)
        my_notes = self._extract_my_notes(content)
        full_transcript = self._extract_full_transcript(content)
        
        # Combine all content into notes
        notes = self._build_notes(enhanced_notes, my_notes, full_transcript)
        
        # Use metadata for core fields, fallback to filename parsing
        meeting_id = metadata.get('granola_note_id', file_path.stem)
        company = self._extract_company_name(title, enhanced_notes)
        date_obj = self._parse_timestamp(metadata.get('calendar_event_time') or date_str)
        participants = self._extract_participants(metadata.get('attendees', ''), content)
        
        return Transcript(
            meeting_id=meeting_id,
            date=date_obj,
            company=company,
            participants=participants,
            desk='Unknown',
            notes=notes,
            source='granola_drive',
            
            # Granola metadata
            granola_note_id=metadata.get('granola_note_id'),
            title=metadata.get('title'),
            creator_name=metadata.get('creator_name'),
            creator_email=metadata.get('creator_email'),
            calendar_event_title=metadata.get('calendar_event_title'),
            calendar_event_id=metadata.get('calendar_event_id'),
            calendar_event_time=metadata.get('calendar_event_time'),
            granola_link=metadata.get('granola_link'),
            file_created_timestamp=metadata.get('file_created_timestamp'),
            zapier_step_id=metadata.get('zapier_step_id'),
            
            # Content sections
            enhanced_notes=enhanced_notes,
            my_notes=my_notes,
            full_transcript=full_transcript
        )
    
    def _extract_json_metadata(self, content: str) -> dict:
        """Extract JSON metadata from the file header"""
        lines = content.split('\n')
        
        # Look for JSON block starting with ```json
        json_start = None
        json_end = None
        
        for i, line in enumerate(lines):
            if line.strip() == '```json':
                json_start = i + 1
            elif line.strip() == '```' and json_start is not None:
                json_end = i
                break
        
        if json_start is not None and json_end is not None:
            json_text = '\n'.join(lines[json_start:json_end])
            
            # Fix common JSON formatting issues
            json_text = self._fix_malformed_json(json_text)
            
            try:
                return json.loads(json_text)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse JSON metadata: {e}")
                return {}
        
        return {}
    
    def _fix_malformed_json(self, json_text: str) -> str:
        """Fix common JSON formatting issues from Zapier/Granola"""
        # Fix empty attendees field: "attendees": , -> "attendees": ""
        json_text = re.sub(r'"attendees":\s*,', '"attendees": "",', json_text)
        
        # Fix other empty fields with trailing commas
        json_text = re.sub(r':\s*,', ': "",', json_text)
        
        return json_text
    
    def _parse_filename(self, filename: str) -> Tuple[str, str, str]:
        """Parse filename pattern: [Creator] Title - Extra - Timestamp.txt"""
        match = self.filename_pattern.match(filename)
        if match:
            creator = match.group(1)
            title = match.group(2)
            # Skip extra field (group 3), use timestamp (group 4)
            timestamp = match.group(4)
            return creator, title, timestamp
        
        # Fallback parsing
        parts = filename.replace('.txt', '').split(' - ')
        creator = parts[0].strip('[]') if parts else 'Unknown'
        title = parts[1] if len(parts) > 1 else filename
        timestamp = parts[-1] if len(parts) > 2 else ''
        
        return creator, title, timestamp
    
    def _extract_enhanced_notes(self, content: str) -> str:
        """Extract content from Enhanced Notes section"""
        return self._extract_section(content, "## Enhanced Notes", "## My Notes")
    
    def _extract_my_notes(self, content: str) -> str:
        """Extract content from My Notes section"""
        return self._extract_section(content, "## My Notes", "## Full Transcript")
    
    def _extract_full_transcript(self, content: str) -> str:
        """Extract content from Full Transcript section"""
        lines = content.split('\n')
        start_idx = None
        
        for i, line in enumerate(lines):
            if line.strip() == "## Full Transcript":
                start_idx = i + 1
                break
        
        if start_idx is not None:
            return '\n'.join(lines[start_idx:]).strip()
        
        return ""
    
    def _extract_section(self, content: str, start_marker: str, end_marker: str) -> str:
        """Extract content between two section markers"""
        lines = content.split('\n')
        start_idx = None
        end_idx = None
        
        for i, line in enumerate(lines):
            if line.strip() == start_marker:
                start_idx = i + 1
            elif line.strip() == end_marker and start_idx is not None:
                end_idx = i
                break
        
        if start_idx is not None:
            if end_idx is not None:
                return '\n'.join(lines[start_idx:end_idx]).strip()
            else:
                return '\n'.join(lines[start_idx:]).strip()
        
        return ""
    
    def _extract_company_name(self, title: str, enhanced_notes: str) -> Optional[str]:
        """Extract company name from title or enhanced notes"""
        # Try to extract from title - look for company names
        title_clean = re.sub(r'\s*-\s*.*$', '', title).strip()
        
        # Check if title contains known company patterns
        company_match = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]*)*)\b', title_clean)
        if company_match:
            potential_company = company_match.group(1)
            # Filter out common non-company words
            if potential_company.lower() not in ['meeting', 'call', 'sync', 'test', 'notes']:
                return potential_company
        
        # Look in enhanced notes for company mentions
        lines = enhanced_notes.split('\n')
        for line in lines[:10]:  # Check first 10 lines
            if any(keyword in line.lower() for keyword in ['company:', 'client:', 'organization:']):
                company_match = re.search(r':\s*([^,\n]+)', line)
                if company_match:
                    return company_match.group(1).strip()
        
        return None
    
    def _extract_participants(self, attendees_str: str, content: str) -> List[str]:
        """Extract participants from attendees field or content"""
        participants = []
        
        # First try attendees from JSON metadata
        if attendees_str and attendees_str.strip():
            participants = [p.strip() for p in attendees_str.split(',') if p.strip()]
        
        # If no attendees in metadata, look in content
        if not participants:
            lines = content.split('\n')
            for line in lines[:20]:  # Check first 20 lines
                if 'attendees:' in line.lower() or 'participants:' in line.lower():
                    participants_str = re.sub(r'(attendees:|participants:)', '', line, flags=re.IGNORECASE).strip()
                    participants = [p.strip() for p in re.split(r'[,;]', participants_str) if p.strip()]
                    break
        
        return participants
    
    def _build_notes(self, enhanced_notes: str, my_notes: str, full_transcript: str) -> List[Note]:
        """Build Note objects from all content sections"""
        notes = []
        
        # Process Enhanced Notes as general content (no speaker)
        if enhanced_notes:
            notes.extend(self._parse_content_notes(enhanced_notes))
        
        # Process My Notes as general content (no speaker)  
        if my_notes:
            notes.extend(self._parse_content_notes(my_notes))
        
        # Process Full Transcript with actual speakers
        if full_transcript:
            notes.extend(self._parse_transcript_notes(full_transcript))
        
        return notes
    
    def _parse_content_notes(self, content: str) -> List[Note]:
        """Parse structured notes from Enhanced Notes or My Notes sections without speaker"""
        notes = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('---'):
                continue
            
            # Skip metadata lines
            if any(marker in line for marker in ['**Date:**', '**Creator:**', '**Calendar Event:**', 
                                               '**Attendees:**', '**Granola Note ID:**']):
                continue
            
            # Add meaningful content as notes (no speaker)
            if line and not line.startswith('Chat with meeting transcript:'):
                notes.append(Note(
                    t=None,
                    speaker=None,
                    text=line
                ))
        
        return notes
    
    def _parse_transcript_notes(self, transcript_content: str) -> List[Note]:
        """Parse the full transcript section for speaker notes"""
        notes = []
        lines = transcript_content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('---') or 'Original Granola Link:' in line or 'Synced via Zapier:' in line:
                continue
            
            # Look for speaker patterns like "Me:", "Speaker:", etc.
            speaker_match = re.match(r'^([^:]+):\s*(.+)', line)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                text = speaker_match.group(2).strip()
                
                notes.append(Note(
                    t=None,
                    speaker=speaker,
                    text=text
                ))
            elif line and not line.startswith(('**', '*')):
                # Add non-speaker lines as general notes
                notes.append(Note(
                    t=None,
                    speaker=None,
                    text=line
                ))
        
        return notes
    
    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse ISO timestamp or fallback to current date"""
        if not timestamp_str:
            return datetime.now().date()
        
        # Try parsing ISO format from metadata
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return dt.date()
        except ValueError:
            pass
        
        # Try parsing date from filename format
        try:
            dt = datetime.strptime(timestamp_str, '%Y-%m-%dT%H_%M_%S.%fZ')
            return dt.date()
        except ValueError:
            pass
        
        # Fallback to current date
        return datetime.now().date()