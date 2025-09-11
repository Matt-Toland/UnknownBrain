import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

from ..schemas import Transcript, Note


class HtmlImporter:
    def __init__(self):
        self.timestamp_pattern = re.compile(r'\[?(\d{2}:\d{2}:\d{2}|\d{2}:\d{2})\]?\s*[-:]?\s*([^:]+):\s*(.+)')
        self.speaker_pattern = re.compile(r'^([^:]+):\s*(.+)')
        
    def parse_file(self, file_path: Path) -> Transcript:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'html.parser')
        
        title, date_str, company = self._extract_title_info(soup)
        participants = self._extract_participants(soup)
        notes = self._extract_notes(soup)
        
        meeting_id = file_path.stem
        date_obj = self._parse_date(date_str) if date_str else datetime.now().date()
        
        return Transcript(
            meeting_id=meeting_id,
            date=date_obj,
            company=company,
            participants=participants,
            desk='Unknown',
            notes=notes,
            source='html'
        )
    
    def _extract_title_info(self, soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        title_element = soup.find(['h1', 'h2', 'title'])
        if not title_element:
            return None, None, None
            
        title = title_element.get_text().strip()
        
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', title)
        date_str = date_match.group(1) if date_match else None
        
        if not date_str:
            date_elements = soup.find_all(text=re.compile(r'\d{4}-\d{2}-\d{2}'))
            if date_elements:
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_elements[0])
                date_str = date_match.group(1) if date_match else None
        
        company_match = re.match(r'([^-—]+)[-—]', title)
        company = company_match.group(1).strip() if company_match else None
        
        return title, date_str, company
    
    def _extract_participants(self, soup: BeautifulSoup) -> List[str]:
        participants = []
        
        participants_elements = soup.find_all(text=re.compile(r'(Participants|Attendees):'))
        for element in participants_elements:
            parent = element.parent
            if parent:
                text = parent.get_text()
                participants_str = re.sub(r'(Participants|Attendees):\s*', '', text).strip()
                participants = [p.strip() for p in re.split(r'[,;]', participants_str) if p.strip()]
                break
        
        return participants
    
    def _extract_notes(self, soup: BeautifulSoup) -> List[Note]:
        notes = []
        
        content_divs = soup.find_all(['div', 'p'], class_=lambda x: x and any(cls in str(x).lower() for cls in ['meeting', 'notes', 'content', 'timestamp']))
        
        if not content_divs:
            content_divs = soup.find_all(['p', 'div'])
        
        for element in content_divs:
            text = element.get_text().strip()
            if not text or len(text) < 10:
                continue
                
            if any(keyword in text.lower() for keyword in ['participants:', 'attendees:', 'date:', 'key metrics', 'action items']):
                continue
            
            timestamp_match = self.timestamp_pattern.match(text)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                speaker = timestamp_match.group(2).strip()
                note_text = timestamp_match.group(3).strip()
                
                notes.append(Note(
                    t=timestamp,
                    speaker=speaker,
                    text=note_text
                ))
            else:
                speaker_match = self.speaker_pattern.match(text)
                if speaker_match:
                    speaker = speaker_match.group(1).strip()
                    note_text = speaker_match.group(2).strip()
                    
                    if len(note_text) > 10:
                        notes.append(Note(
                            t=None,
                            speaker=speaker,
                            text=note_text
                        ))
                elif not text.startswith(('Meeting Date', 'Date:', 'Attendees')):
                    notes.append(Note(
                        t=None,
                        speaker=None,
                        text=text
                    ))
        
        return notes
    
    def _parse_date(self, date_str: str) -> datetime:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return datetime.now().date()