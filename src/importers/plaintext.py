import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

from ..schemas import Transcript, Note


class PlaintextImporter:
    def __init__(self):
        self.timestamp_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2}|\d{2}:\d{2})\]\s*([^:]+):\s*(.+)')
        self.speaker_pattern = re.compile(r'^([^:]+):\s*(.+)')
        
    def parse_file(self, file_path: Path) -> Transcript:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        title, date_str, company = self._extract_title_info(content)
        participants = self._extract_participants(content)
        notes = self._extract_notes(content)
        
        meeting_id = file_path.stem
        date_obj = self._parse_date(date_str) if date_str else datetime.now().date()
        
        return Transcript(
            meeting_id=meeting_id,
            date=date_obj,
            company=company,
            participants=participants,
            desk='Unknown',
            notes=notes,
            source='plaintext'
        )
    
    def _extract_title_info(self, content: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        lines = content.split('\n')
        
        title_line = None
        date_str = None
        company = None
        
        # First, try to find a title line with separator
        for line in lines[:5]:
            if ' - ' in line or ' — ' in line:
                title_line = line.strip()
                break
        
        # Extract company from title line if found
        if title_line:
            company_match = re.match(r'([^-—]+)[-—]', title_line)
            company = company_match.group(1).strip() if company_match else None
            
            # Try to find date in title line
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', title_line)
            if date_match:
                date_str = date_match.group(1)
        
        # If no date found in title, search broader in early content
        if not date_str:
            for line in lines[:10]:
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if date_match:
                    date_str = date_match.group(1)
                    break
        
        # Try to extract company from first non-empty line if not found in title
        if not company and lines:
            first_line = lines[0].strip()
            if first_line and not re.search(r'^\d{4}-\d{2}-\d{2}', first_line):
                # Remove date from first line if present and use rest as company
                company_line = re.sub(r'\d{4}-\d{2}-\d{2}', '', first_line).strip()
                company_line = re.sub(r'[-—]\s*.*$', '', company_line).strip()
                if company_line:
                    company = company_line
        
        return title_line, date_str, company
    
    def _extract_participants(self, content: str) -> List[str]:
        participants = []
        lines = content.split('\n')
        
        for line in lines[:10]:
            if 'Participants:' in line or 'Attendees:' in line:
                participants_str = re.sub(r'(Participants:|Attendees:)', '', line).strip()
                participants = [p.strip() for p in re.split(r'[,;]', participants_str) if p.strip()]
                break
            elif line.strip() and ',' in line and '(' in line:
                participants = [p.strip() for p in line.split(',') if p.strip()]
                break
        
        return participants
    
    def _extract_notes(self, content: str) -> List[Note]:
        notes = []
        lines = content.split('\n')
        
        # Handle YAML frontmatter and content delimiters
        in_yaml_frontmatter = False
        content_started = False
        dash_count = 0
        
        for line in lines:
            # Count all --- delimiters
            if line.strip() == '---':
                dash_count += 1
                
                if dash_count == 1:
                    # First --- starts YAML frontmatter
                    in_yaml_frontmatter = True
                    continue
                elif dash_count == 2:
                    # Second --- ends YAML frontmatter
                    in_yaml_frontmatter = False
                    continue
                else:
                    # Third --- (or beyond) starts content
                    content_started = True
                    continue
            
            # Skip everything inside YAML frontmatter
            if in_yaml_frontmatter:
                continue
                
            if line.strip() in ['___']:
                content_started = True
                continue
                
            if not content_started and not any(keyword in line.lower() for keyword in ['date:', 'participants:', 'attendees:']):
                content_started = True
            
            if not content_started or not line.strip():
                continue
                
            if line.startswith(('Date:', 'Participants:', 'Attendees:')) or 'Key challenges:' in line or 'Metrics:' in line or 'Business context:' in line or 'Performance metrics:' in line:
                continue
            
            timestamp_match = self.timestamp_pattern.match(line.strip())
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                speaker = timestamp_match.group(2).strip()
                text = timestamp_match.group(3).strip()
                
                notes.append(Note(
                    t=timestamp,
                    speaker=speaker,
                    text=text
                ))
            else:
                speaker_match = self.speaker_pattern.match(line.strip())
                if speaker_match:
                    speaker = speaker_match.group(1).strip()
                    text = speaker_match.group(2).strip()
                    
                    notes.append(Note(
                        t=None,
                        speaker=speaker,
                        text=text
                    ))
                elif line.strip() and not line.startswith(('-', '•', '*')) and not ':' in line[-20:]:
                    notes.append(Note(
                        t=None,
                        speaker=None,
                        text=line.strip()
                    ))
        
        return notes
    
    def _parse_date(self, date_str: str) -> datetime:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return datetime.now().date()