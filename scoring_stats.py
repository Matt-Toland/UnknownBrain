"""
Generate scoring statistics report

Usage:
    python scoring_stats.py
"""

import os
from google.cloud import bigquery
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

load_dotenv()

console = Console()

def generate_scoring_stats():
    """Generate comprehensive scoring statistics"""

    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'gcp_service_account_creds.json'
    client = bigquery.Client(project='angular-stacker-471711-k4')

    # Overall distribution
    query_distribution = """
    SELECT
      total_qualified_sections,
      COUNT(*) as meeting_count,
      ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
    FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
    GROUP BY total_qualified_sections
    ORDER BY total_qualified_sections DESC
    """

    # Criteria pass rates
    query_criteria = """
    SELECT
      SUM(CASE WHEN JSON_VALUE(now, '$.qualified') = 'true' THEN 1 ELSE 0 END) as now_count,
      SUM(CASE WHEN JSON_VALUE(next, '$.qualified') = 'true' THEN 1 ELSE 0 END) as next_count,
      SUM(CASE WHEN JSON_VALUE(measure, '$.qualified') = 'true' THEN 1 ELSE 0 END) as measure_count,
      SUM(CASE WHEN JSON_VALUE(blocker, '$.qualified') = 'true' THEN 1 ELSE 0 END) as blocker_count,
      SUM(CASE WHEN JSON_VALUE(fit, '$.qualified') = 'true' THEN 1 ELSE 0 END) as fit_count,
      COUNT(*) as total_meetings,
      ROUND(AVG(total_qualified_sections), 2) as avg_score
    FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
    """

    # Get results
    dist_results = list(client.query(query_distribution).result())
    criteria_results = list(client.query(query_criteria).result())[0]

    # Display distribution
    console.print("\n[bold]Score Distribution[/bold]")
    table = Table()
    table.add_column("Score", style="cyan")
    table.add_column("Count", style="magenta")
    table.add_column("Percentage", style="yellow")

    for row in dist_results:
        table.add_row(
            f"{row.total_qualified_sections}/5",
            str(row.meeting_count),
            f"{row.percentage}%"
        )

    console.print(table)

    # Display criteria pass rates
    console.print("\n[bold]Criteria Pass Rates[/bold]")
    total = criteria_results.total_meetings

    criteria_table = Table()
    criteria_table.add_column("Criterion", style="cyan")
    criteria_table.add_column("Passed", style="magenta")
    criteria_table.add_column("Rate", style="yellow")

    criteria_data = [
        ("NOW (Immediate Hiring)", criteria_results.now_count),
        ("NEXT (Future Vision)", criteria_results.next_count),
        ("MEASURE (Has KPIs)", criteria_results.measure_count),
        ("BLOCKER (Growth Obstacles)", criteria_results.blocker_count),
        ("FIT (UNKNOWN Match)", criteria_results.fit_count)
    ]

    for name, count in criteria_data:
        percentage = (count / total * 100) if total > 0 else 0
        criteria_table.add_row(
            name,
            f"{count}/{total}",
            f"{percentage:.1f}%"
        )

    console.print(criteria_table)

    # Summary stats
    console.print(f"\n[bold]Summary Statistics[/bold]")
    console.print(f"  Total meetings: {total}")
    console.print(f"  Average score: {criteria_results.avg_score}/5")

    qualified_count = sum(row.meeting_count for row in dist_results if row.total_qualified_sections >= 3)
    qualified_pct = (qualified_count / total * 100) if total > 0 else 0
    console.print(f"  Qualified (≥3/5): {qualified_count}/{total} ({qualified_pct:.1f}%)")

    high_score_count = sum(row.meeting_count for row in dist_results if row.total_qualified_sections >= 4)
    high_score_pct = (high_score_count / total * 100) if total > 0 else 0
    console.print(f"  High scores (≥4/5): {high_score_count}/{total} ({high_score_pct:.1f}%)")

    # Warning if too many high scores
    if high_score_pct > 50:
        console.print(f"\n[yellow]⚠️  Warning: {high_score_pct:.1f}% of meetings scored 4-5/5[/yellow]")
        console.print("[yellow]   This may indicate overly lenient scoring criteria[/yellow]")


if __name__ == "__main__":
    generate_scoring_stats()
