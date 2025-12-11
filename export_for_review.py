"""
Export high-scoring meetings for scoring criteria review

Usage:
    python export_for_review.py --min-score 4 --limit 50
"""

import os
import json
import csv
from pathlib import Path
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

def export_meetings_for_review(min_score: int = 4, limit: int = 50, output_path: str = "scoring_review.csv"):
    """Export meetings with evidence for manual review"""

    # Initialize BigQuery
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'gcp_service_account_creds.json'
    client = bigquery.Client(project='angular-stacker-471711-k4')

    query = f"""
    SELECT
      meeting_id,
      JSON_VALUE(client_info, '$.client') as client,
      title,
      creator_name,
      date,
      total_qualified_sections,
      qualified,

      -- NOW
      JSON_VALUE(now, '$.qualified') as now_qualified,
      JSON_VALUE(now, '$.reason') as now_reason,
      JSON_VALUE(now, '$.summary') as now_summary,
      JSON_VALUE(now, '$.evidence') as now_evidence,

      -- NEXT
      JSON_VALUE(next, '$.qualified') as next_qualified,
      JSON_VALUE(next, '$.reason') as next_reason,
      JSON_VALUE(next, '$.summary') as next_summary,
      JSON_VALUE(next, '$.evidence') as next_evidence,

      -- MEASURE
      JSON_VALUE(measure, '$.qualified') as measure_qualified,
      JSON_VALUE(measure, '$.reason') as measure_reason,
      JSON_VALUE(measure, '$.summary') as measure_summary,
      JSON_VALUE(measure, '$.evidence') as measure_evidence,

      -- BLOCKER
      JSON_VALUE(blocker, '$.qualified') as blocker_qualified,
      JSON_VALUE(blocker, '$.reason') as blocker_reason,
      JSON_VALUE(blocker, '$.summary') as blocker_summary,
      JSON_VALUE(blocker, '$.evidence') as blocker_evidence,

      -- FIT
      JSON_VALUE(fit, '$.qualified') as fit_qualified,
      JSON_VALUE(fit, '$.reason') as fit_reason,
      JSON_VALUE(fit, '$.summary') as fit_summary,
      JSON_VALUE(fit, '$.evidence') as fit_evidence,
      JSON_VALUE(fit, '$.services') as fit_services

    FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
    WHERE total_qualified_sections >= {min_score}
    ORDER BY scored_at DESC
    LIMIT {limit}
    """

    print(f"Exporting meetings with score >= {min_score}...")
    results = client.query(query).result()

    # Write to CSV
    rows = [dict(row) for row in results]

    if not rows:
        print("No meetings found matching criteria")
        return

    # Write CSV with all fields
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Exported {len(rows)} meetings to {output_path}")

    # Print summary stats
    total = len(rows)
    score_5 = sum(1 for r in rows if r['total_qualified_sections'] == 5)
    score_4 = sum(1 for r in rows if r['total_qualified_sections'] == 4)

    print(f"\nScore distribution:")
    print(f"  5/5: {score_5} ({score_5/total*100:.1f}%)")
    print(f"  4/5: {score_4} ({score_4/total*100:.1f}%)")

    # Count by criteria
    now_count = sum(1 for r in rows if r['now_qualified'] == 'true')
    next_count = sum(1 for r in rows if r['next_qualified'] == 'true')
    measure_count = sum(1 for r in rows if r['measure_qualified'] == 'true')
    blocker_count = sum(1 for r in rows if r['blocker_qualified'] == 'true')
    fit_count = sum(1 for r in rows if r['fit_qualified'] == 'true')

    print(f"\nCriteria pass rates:")
    print(f"  NOW:     {now_count}/{total} ({now_count/total*100:.1f}%)")
    print(f"  NEXT:    {next_count}/{total} ({next_count/total*100:.1f}%)")
    print(f"  MEASURE: {measure_count}/{total} ({measure_count/total*100:.1f}%)")
    print(f"  BLOCKER: {blocker_count}/{total} ({blocker_count/total*100:.1f}%)")
    print(f"  FIT:     {fit_count}/{total} ({fit_count/total*100:.1f}%)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Export meetings for scoring review')
    parser.add_argument('--min-score', type=int, default=4, help='Minimum score to export (default: 4)')
    parser.add_argument('--limit', type=int, default=50, help='Max meetings to export (default: 50)')
    parser.add_argument('--output', type=str, default='scoring_review.csv', help='Output CSV file')

    args = parser.parse_args()

    export_meetings_for_review(args.min_score, args.limit, args.output)
