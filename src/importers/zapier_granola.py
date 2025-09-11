import json
import yaml
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import re
from bs4 import BeautifulSoup

from ..schemas import Transcript, Note
from .markdown import MarkdownImporter
from .html import HtmlImporter
from .plaintext import PlaintextImporter


class ZapierGranolaImporter:
    def __init__(self):
        self.mapping_config = self._load_mapping_config()
        self.markdown_importer = MarkdownImporter()
        self.html_importer = HtmlImporter()
        self.plaintext_importer = PlaintextImporter()
        
    def _load_mapping_config(self) -> Dict[str, Any]:
        mapping_path = Path(__file__).parent / "mapping.yaml"
        with open(mapping_path, 'r') as f:
            return yaml.safe_load(f)
    
    def parse_zapier_payload(self, payload: Dict[str, Any]) -> Transcript:
        meeting_id = self._extract_field(payload, 'meeting_id') or f"zap-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        company = self._extract_field(payload, 'company')
        date_str = self._extract_field(payload, 'date')
        participants = self._extract_participants(payload)
        content = self._extract_field(payload, 'content') or ""
        title = self._extract_field(payload, 'title')
        
        date_obj = self._parse_date(date_str) if date_str else datetime.now().date()
        
        if not company and title:
            company_match = re.match(r'([^-—]+)[-—]', title)
            company = company_match.group(1).strip() if company_match else None
        
        content_type = self._detect_content_type(content, payload)
        notes = self._parse_content(content, content_type, meeting_id)
        
        return Transcript(
            meeting_id=meeting_id,
            date=date_obj,
            company=company,
            participants=participants,
            desk=self.mapping_config['default_values']['desk'],
            notes=notes,
            source=self.mapping_config['default_values']['source']
        )
    
    def _extract_field(self, payload: Dict[str, Any], field_type: str) -> Optional[str]:
        possible_fields = self.mapping_config['zapier_granola'][field_type]
        
        for field in possible_fields:
            if field in payload and payload[field]:
                value = payload[field]
                if isinstance(value, str):
                    return value.strip()
                elif isinstance(value, (int, float)):
                    return str(value)
        
        return None
    
    def _extract_participants(self, payload: Dict[str, Any]) -> List[str]:
        participants_raw = self._extract_field(payload, 'participants')
        if not participants_raw:
            return []
        
        if isinstance(participants_raw, list):
            return [str(p).strip() for p in participants_raw if p]
        
        participants = [p.strip() for p in re.split(r'[,;]', participants_raw) if p.strip()]
        return participants
    
    def _detect_content_type(self, content: str, payload: Dict[str, Any]) -> str:
        if not content:
            return 'plaintext'
        
        content_lower = content.lower().strip()
        
        if content_lower.startswith(('<!doctype', '<html', '<div', '<p')) or '</' in content:
            return 'html'
        
        if content_lower.startswith('#') or '**' in content or '##' in content:
            return 'markdown'
        
        return 'plaintext'
    
    def _parse_content(self, content: str, content_type: str, meeting_id: str) -> List[Note]:
        if not content:
            return []
        
        # For markdown content, ensure it has the expected structure
        if content_type == 'markdown' and '---' not in content:
            # Add separator after any header section
            lines = content.split('\n')
            header_lines = []
            content_lines = []
            
            for i, line in enumerate(lines):
                if line.strip().startswith('#') or ('Participants:' in line):
                    header_lines.append(line)
                else:
                    content_lines = lines[i:]
                    break
            
            if header_lines:
                content = '\n'.join(header_lines) + '\n---\n' + '\n'.join(content_lines)
            else:
                content = '---\n' + content
        
        temp_file = Path(f"/tmp/{meeting_id}_temp.{content_type}")
        temp_file.write_text(content)
        
        try:
            if content_type == 'html':
                transcript = self.html_importer.parse_file(temp_file)
            elif content_type == 'markdown':
                transcript = self.markdown_importer.parse_file(temp_file)
            else:
                transcript = self.plaintext_importer.parse_file(temp_file)
            
            return transcript.notes
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    def _parse_date(self, date_str: str) -> date:
        if not date_str:
            return datetime.now().date()
        
        date_formats = [
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%d/%m/%Y',
            '%m/%d/%Y',
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        return datetime.now().date()
    
    def parse_fixture_file(self, file_path: Path) -> Transcript:
        with open(file_path, 'r') as f:
            payload = json.load(f)
        return self.parse_zapier_payload(payload)