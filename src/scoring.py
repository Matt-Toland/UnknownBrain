import json
import csv
from pathlib import Path
from typing import List, Dict
from datetime import date, datetime

from .schemas import ScoreResult, Transcript, ScoredTranscript


class OutputGenerator:
    def __init__(self):
        pass
    
    def generate_json_output(self, results: List[ScoreResult], output_path: Path):
        output_data = [result.model_dump(mode='json') for result in results]
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2, default=self._json_serializer)
    
    def generate_csv_output(self, results: List[ScoreResult], output_path: Path):
        if not results:
            return
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            
            writer.writerow([
                'meeting_id', 'company', 'date', 'total_score', 'qualified',
                'now_score', 'now_evidence', 'now_timestamp',
                'next_score', 'next_evidence', 'next_timestamp', 
                'measure_score', 'measure_evidence', 'measure_timestamp',
                'blocker_score', 'blocker_evidence', 'blocker_timestamp',
                'fit_score', 'fit_labels', 'fit_evidence', 'fit_timestamp'
            ])
            
            for result in results:
                writer.writerow([
                    result.meeting_id,
                    result.company or '',
                    result.date.isoformat(),
                    result.total_score,
                    result.qualified,
                    result.checks['now']['score'],
                    result.checks['now']['evidence_line'] or '',
                    result.checks['now']['timestamp'] or '',
                    result.checks['next']['score'], 
                    result.checks['next']['evidence_line'] or '',
                    result.checks['next']['timestamp'] or '',
                    result.checks['measure']['score'],
                    result.checks['measure']['evidence_line'] or '',
                    result.checks['measure']['timestamp'] or '',
                    result.checks['blocker']['score'],
                    result.checks['blocker']['evidence_line'] or '',
                    result.checks['blocker']['timestamp'] or '',
                    result.checks['fit']['score'],
                    '; '.join(result.checks['fit'].get('fit_labels', [])),
                    result.checks['fit']['evidence_line'] or '',
                    result.checks['fit']['timestamp'] or ''
                ])
    
    def generate_leaderboard(self, results: List[ScoreResult], output_path: Path):
        if not results:
            return
        
        qualified_count = sum(1 for r in results if r.qualified)
        qualified_pct = (qualified_count / len(results)) * 100 if results else 0
        
        fit_counts = {'Talent': 0, 'Evolve': 0, 'Ventures': 0}
        for result in results:
            for label in result.checks['fit'].get('fit_labels', []):
                if label in fit_counts:
                    fit_counts[label] += 1
        
        markdown_content = f"""# UNKNOWN Brain - Meeting Transcript Leaderboard

## Summary Statistics
- **Total Meetings Analyzed**: {len(results)}
- **Qualified Meetings** (≥3/5 score): {qualified_count} ({qualified_pct:.1f}%)

## Fit Category Distribution
- **Talent**: {fit_counts['Talent']} meetings
- **Evolve**: {fit_counts['Evolve']} meetings  
- **Ventures**: {fit_counts['Ventures']} meetings

## Ranked Results

| Rank | Meeting ID | Company | Date | Score | Now | Next | Measure | Blocker | Fit | Fit Labels |
|------|------------|---------|------|-------|-----|------|---------|---------|-----|------------|
"""
        
        for i, result in enumerate(results, 1):
            fit_labels = ', '.join(result.checks['fit'].get('fit_labels', []))
            markdown_content += f"| {i} | {result.meeting_id} | {result.company or 'N/A'} | {result.date} | **{result.total_score}/5** | {result.checks['now']['score']} | {result.checks['next']['score']} | {result.checks['measure']['score']} | {result.checks['blocker']['score']} | {result.checks['fit']['score']} | {fit_labels or 'None'} |\n"
        
        markdown_content += f"""

## Qualified Meetings Detail

"""
        
        qualified_results = [r for r in results if r.qualified]
        for result in qualified_results:
            markdown_content += f"""### {result.meeting_id} - {result.company or 'Unknown Company'} ({result.total_score}/5)

**Date**: {result.date}

**Evidence Summary**:
"""
            for check_name, check_data in result.checks.items():
                if check_data['score'] > 0 and check_data.get('evidence_line'):
                    timestamp = f" [{check_data['timestamp']}]" if check_data.get('timestamp') else ""
                    markdown_content += f"- **{check_name.title()}**{timestamp}: {check_data['evidence_line']}\n"
            
            markdown_content += "\n---\n\n"
        
        with open(output_path, 'w') as f:
            f.write(markdown_content)
    
    def generate_bq_output(self, results: List[ScoreResult], transcripts: Dict[str, Transcript], 
                          output_path: Path, llm_model: str):
        """Generate JSONL output for BigQuery import"""
        scored_transcripts = []
        
        for result in results:
            transcript = transcripts.get(result.meeting_id)
            if not transcript:
                continue
                
            # Create ScoredTranscript by combining transcript and score data
            scored = ScoredTranscript(
                # Core transcript fields
                meeting_id=result.meeting_id,
                date=result.date,
                company=result.company,
                participants=transcript.participants,
                desk=transcript.desk,
                source=transcript.source,
                
                # Granola metadata
                granola_note_id=transcript.granola_note_id,
                title=transcript.title,
                creator_name=transcript.creator_name,
                creator_email=transcript.creator_email,
                calendar_event_title=transcript.calendar_event_title,
                calendar_event_id=transcript.calendar_event_id,
                calendar_event_time=transcript.calendar_event_time,
                granola_link=transcript.granola_link,
                file_created_timestamp=transcript.file_created_timestamp,
                zapier_step_id=transcript.zapier_step_id,
                
                # Content sections
                enhanced_notes=transcript.enhanced_notes,
                my_notes=transcript.my_notes,
                full_transcript=transcript.full_transcript,
                
                # Scoring results
                total_score=result.total_score,
                qualified=result.qualified,
                
                # Individual check results
                now_score=result.checks['now']['score'],
                now_evidence=result.checks['now']['evidence_line'],
                now_timestamp=result.checks['now']['timestamp'],
                
                next_score=result.checks['next']['score'],
                next_evidence=result.checks['next']['evidence_line'],
                next_timestamp=result.checks['next']['timestamp'],
                
                measure_score=result.checks['measure']['score'],
                measure_evidence=result.checks['measure']['evidence_line'],
                measure_timestamp=result.checks['measure']['timestamp'],
                
                blocker_score=result.checks['blocker']['score'],
                blocker_evidence=result.checks['blocker']['evidence_line'],
                blocker_timestamp=result.checks['blocker']['timestamp'],
                
                fit_score=result.checks['fit']['score'],
                fit_labels=result.checks['fit'].get('fit_labels', []),
                fit_evidence=result.checks['fit']['evidence_line'],
                fit_timestamp=result.checks['fit']['timestamp'],
                
                # Processing metadata
                scored_at=datetime.now(),
                llm_model=llm_model
            )
            
            scored_transcripts.append(scored)
        
        # Write as JSONL (newline-delimited JSON)
        with open(output_path, 'w') as f:
            for scored in scored_transcripts:
                json_line = json.dumps(scored.model_dump(mode='json'), default=self._json_serializer)
                f.write(json_line + '\n')
    
    def _json_serializer(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")