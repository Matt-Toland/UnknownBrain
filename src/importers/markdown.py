import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
import frontmatter

from ..schemas import Transcript, Note


class MarkdownImporter:
    def __init__(self):
        self.timestamp_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2}|\d{2}:\d{2})\]\s*([^:]+):\s*(.+)')
        self.speaker_pattern = re.compile(r'^([^:]+):\s*(.+)')
        
    def parse_file(self, file_path: Path) -> Transcript:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        post = frontmatter.loads(content)
        
        title, date_str, company = self._extract_title_info(post.content)
        participants = self._extract_participants(post.content)
        notes = self._extract_notes(post.content)
        
        meeting_id = file_path.stem
        date_obj = self._parse_date(date_str) if date_str else datetime.now().date()
        
        return Transcript(
            meeting_id=meeting_id,
            date=date_obj,
            company=company,
            participants=participants,
            desk=post.metadata.get('desk', 'Unknown'),
            notes=notes,
            source='markdown'
        )
    
    def _extract_title_info(self, content: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        lines = content.split('\n')
        title_line = next((line for line in lines if line.startswith('#')), None)
        
        if not title_line:
            return None, None, None
            
        title = title_line.lstrip('#').strip()
        
        date_match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', title)
        date_str = date_match.group(1) if date_match else None
        
        company_match = re.match(r'([^—]+)\s*—', title)
        company = company_match.group(1).strip() if company_match else None
        
        return title, date_str, company
    
    def _extract_participants(self, content: str) -> List[str]:
        participants = []
        lines = content.split('\n')
        
        for line in lines:
            if line.startswith('Participants:'):
                participants_str = line.replace('Participants:', '').strip()
                participants = [p.strip() for p in participants_str.split(';') if p.strip()]
                break
        
        return participants
    
    def _extract_notes(self, content: str) -> List[Note]:
        notes = []
        lines = content.split('\n')
        
        content_started = False
        for line in lines:
            if line.strip() == '---':
                content_started = True
                continue
                
            if not content_started or not line.strip():
                continue
                
            if line.startswith('#') or line.startswith('Participants:') or line.startswith('Metrics:'):
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
                elif line.strip() and not line.startswith(('Key metrics:', 'Metrics:', 'Focus areas:', 'Timeline:', 'Business context:', 'Performance metrics:', 'Action Items:', 'Major blockers:', 'Next steps:', 'Focus:')):
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