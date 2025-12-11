"""
Export recent meetings from BigQuery to JSON for testing sales assessment.
"""

import json
from pathlib import Path
from datetime import date
from src.bq_loader import BigQueryLoader
from rich.console import Console

console = Console()

def export_meetings(limit: int = 5, output_dir: str = "data/json_test"):
    """Export recent meetings from BigQuery to JSON files."""

    loader = BigQueryLoader()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Query for recent meetings with full transcript data
    query = f'''
    SELECT
        meeting_id,
        date,
        participants,
        desk,
        source,
        creator_name,
        creator_email,
        title,
        calendar_event_title,
        granola_note_id,
        calendar_event_id,
        calendar_event_time,
        granola_link,
        file_created_timestamp,
        zapier_step_id,
        enhanced_notes,
        my_notes,
        full_transcript
    FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
    WHERE full_transcript IS NOT NULL
      AND LENGTH(full_transcript) > 1000
      AND creator_name IS NOT NULL
    ORDER BY date DESC
    LIMIT {limit}
    '''

    console.print(f'[blue]Fetching {limit} most recent meetings from BigQuery...[/blue]')
    results = loader.client.query(query).result()

    exported_count = 0
    for row in results:
        # Build transcript JSON
        transcript = {
            "meeting_id": row.meeting_id,
            "date": row.date.isoformat() if isinstance(row.date, date) else str(row.date),
            "company": None,  # Will be extracted by LLM
            "participants": row.participants if row.participants else [],
            "desk": row.desk or "Unknown",
            "notes": [],  # Legacy field, empty for Granola imports
            "source": row.source or "bigquery-export",

            # Granola metadata
            "granola_note_id": row.granola_note_id,
            "title": row.title,
            "creator_name": row.creator_name,
            "creator_email": row.creator_email,
            "calendar_event_title": row.calendar_event_title,
            "calendar_event_id": row.calendar_event_id,
            "calendar_event_time": row.calendar_event_time.isoformat() if row.calendar_event_time else None,
            "granola_link": row.granola_link,
            "file_created_timestamp": str(row.file_created_timestamp) if row.file_created_timestamp else None,
            "zapier_step_id": str(row.zapier_step_id) if row.zapier_step_id else None,

            # Content sections
            "enhanced_notes": row.enhanced_notes,
            "my_notes": row.my_notes,
            "full_transcript": row.full_transcript
        }

        # Create filename from meeting_id (sanitize for filesystem)
        filename = row.meeting_id.replace('/', '_').replace('\\', '_')[:100] + '.json'
        file_path = output_path / filename

        with open(file_path, 'w') as f:
            json.dump(transcript, f, indent=2)

        console.print(f'[green]✓[/green] Exported: {row.title or row.meeting_id[:50]} (by {row.creator_name})')
        exported_count += 1

    console.print(f'\n[bold green]Exported {exported_count} meetings to {output_path}/[/bold green]')
    return exported_count

if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "data/json_test"
    export_meetings(limit=limit, output_dir=output_dir)
