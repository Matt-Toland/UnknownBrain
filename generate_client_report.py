#!/usr/bin/env python3
"""
Generate client-ready scoring results report from BigQuery
"""
import json
import csv
import subprocess
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any
import os

class ClientReportGenerator:
    def __init__(self):
        self.results = []
        self.output_dir = Path("client_reports")
        self.output_dir.mkdir(exist_ok=True)

    def extract_bq_results(self, date_filter: str = "2025-09-28") -> List[Dict]:
        """Extract results from BigQuery with proper JSON parsing"""
        query = f"""
        SELECT
            meeting_id,
            title,
            date,
            participants,
            total_qualified_sections,
            qualified,
            now,
            next,
            measure,
            blocker,
            fit,
            challenges,
            results,
            offering,
            scored_at,
            llm_model
        FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
        WHERE scored_at >= TIMESTAMP('{date_filter}')
        ORDER BY total_qualified_sections DESC, scored_at DESC
        """

        # Run BigQuery query and save to JSON
        cmd = [
            "bq", "query",
            "--use_legacy_sql=false",
            "--format=json",
            "--max_rows=100",
            query
        ]

        # Set up environment with Google Cloud SDK
        env = os.environ.copy()
        env["PATH"] = f"/Users/matt/google-cloud-sdk/bin:{env.get('PATH', '')}"

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                print(f"Error running BigQuery: {result.stderr}")
                return []

            # Parse JSON results
            raw_results = json.loads(result.stdout)

            # Process each result to extract nested JSON fields
            processed_results = []
            for row in raw_results:
                # Parse JSON fields if they exist and are not None
                def safe_json_parse(field):
                    if field and field != "null":
                        try:
                            return json.loads(field)
                        except:
                            return {}
                    return {}

                processed_row = {
                    'meeting_id': row.get('meeting_id', ''),
                    'title': row.get('title', ''),
                    'date': row.get('date', ''),
                    'participants': row.get('participants', []),
                    'total_qualified_sections': int(row.get('total_qualified_sections', 0)),
                    'qualified': row.get('qualified') == 'true',
                    'scored_at': row.get('scored_at', ''),
                    'llm_model': row.get('llm_model', ''),
                    'now': safe_json_parse(row.get('now')),
                    'next': safe_json_parse(row.get('next')),
                    'measure': safe_json_parse(row.get('measure')),
                    'blocker': safe_json_parse(row.get('blocker')),
                    'fit': safe_json_parse(row.get('fit')),
                    'challenges': row.get('challenges', []),
                    'results': row.get('results', []),
                    'offering': row.get('offering', '')
                }
                processed_results.append(processed_row)

            self.results = processed_results
            return processed_results

        except Exception as e:
            print(f"Error extracting BigQuery results: {e}")
            return []

    def generate_executive_summary(self) -> str:
        """Generate executive summary statistics"""
        if not self.results:
            return "No results available"

        total_meetings = len(self.results)
        qualified_meetings = sum(1 for r in self.results if r['qualified'])
        qualification_rate = (qualified_meetings / total_meetings * 100) if total_meetings > 0 else 0

        # Score distribution
        score_dist = {}
        for r in self.results:
            score = r['total_qualified_sections']
            score_dist[score] = score_dist.get(score, 0) + 1

        # Top opportunities (5/5 scores)
        top_opportunities = [r for r in self.results if r['total_qualified_sections'] == 5]

        # Category breakdown from fit services/labels
        fit_categories = {'access': 0, 'transform': 0, 'ventures': 0, 'talent': 0, 'evolve': 0}
        for r in self.results:
            fit_data = r.get('fit', {})
            if isinstance(fit_data, dict):
                # Try both 'services' and 'fit_labels' fields
                services = fit_data.get('services', [])
                fit_labels = fit_data.get('fit_labels', [])
                labels = services if services else fit_labels
                if labels:
                    for label in labels:
                        if label.lower() in fit_categories:
                            fit_categories[label.lower()] += 1

        current_date_exec = datetime.now().strftime('%B %d, %Y')
        summary = f"""
**UNKNOWN Brain - Transcript Analysis Results**
**Analysis Date**: {current_date_exec}

**Executive Summary:**
• **{total_meetings} meetings analyzed** using GPT-5-mini model
• **{qualified_meetings} qualified opportunities** identified ({qualification_rate:.1f}% qualification rate)
• **{len(top_opportunities)} high-priority prospects** (perfect 5/5 scores)
• **{score_dist.get(4, 0)} strong prospects** (4/5 scores)
• **{score_dist.get(3, 0)} moderate prospects** (3/5 scores)

**Service Category Breakdown:**
• Access: {fit_categories['access']} opportunities
• Transform: {fit_categories['transform']} opportunities
• Ventures: {fit_categories['ventures']} opportunities
• Talent: {fit_categories['talent']} opportunities
• Evolve: {fit_categories['evolve']} opportunities
"""
        return summary

    def generate_detailed_csv(self) -> str:
        """Generate detailed CSV with all scoring data"""
        csv_path = self.output_dir / "detailed_scoring_results.csv"

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'Meeting ID', 'Title', 'Date', 'Participants', 'Total Score', 'Qualified',
                'NOW Score', 'NOW Evidence', 'NOW Reason', 'NOW Summary',
                'NEXT Score', 'NEXT Evidence', 'NEXT Reason', 'NEXT Summary',
                'MEASURE Score', 'MEASURE Evidence', 'MEASURE Reason', 'MEASURE Summary',
                'BLOCKER Score', 'BLOCKER Evidence', 'BLOCKER Reason', 'BLOCKER Summary',
                'FIT Score', 'FIT Labels', 'FIT Evidence', 'FIT Reason', 'FIT Summary',
                'Challenges', 'Results', 'Offering',
                'Scored At', 'Model'
            ])

            # Data rows
            for r in self.results:
                def get_evidence(check_data):
                    if isinstance(check_data, dict):
                        return check_data.get('evidence', '')
                    return ''

                def get_reason(check_data):
                    if isinstance(check_data, dict):
                        return check_data.get('reason', '')
                    return ''

                def get_summary(check_data):
                    if isinstance(check_data, dict):
                        return check_data.get('summary', '')
                    return ''

                def get_score(check_data):
                    if isinstance(check_data, dict):
                        qualified = check_data.get('qualified', False)
                        return 1 if qualified else 0
                    return 0

                def get_fit_labels(fit_data):
                    if isinstance(fit_data, dict):
                        # Try both 'services' and 'fit_labels' fields
                        services = fit_data.get('services', [])
                        fit_labels = fit_data.get('fit_labels', [])
                        labels = services if services else fit_labels
                        return '; '.join(labels) if labels else ''
                    return ''

                participants_str = '; '.join(r['participants']) if r['participants'] else ''

                challenges_str = '; '.join(r['challenges']) if r['challenges'] else ''
                results_str = '; '.join(r['results']) if r['results'] else ''

                writer.writerow([
                    r['meeting_id'],
                    r['title'],
                    r['date'],
                    participants_str,
                    r['total_qualified_sections'],
                    'Yes' if r['qualified'] else 'No',
                    get_score(r['now']),
                    get_evidence(r['now']),
                    get_reason(r['now']),
                    get_summary(r['now']),
                    get_score(r['next']),
                    get_evidence(r['next']),
                    get_reason(r['next']),
                    get_summary(r['next']),
                    get_score(r['measure']),
                    get_evidence(r['measure']),
                    get_reason(r['measure']),
                    get_summary(r['measure']),
                    get_score(r['blocker']),
                    get_evidence(r['blocker']),
                    get_reason(r['blocker']),
                    get_summary(r['blocker']),
                    get_score(r['fit']),
                    get_fit_labels(r['fit']),
                    get_evidence(r['fit']),
                    get_reason(r['fit']),
                    get_summary(r['fit']),
                    challenges_str,
                    results_str,
                    r['offering'],
                    r['scored_at'],
                    r['llm_model']
                ])

        return str(csv_path)

    def generate_html_report(self) -> str:
        """Generate HTML report for email sharing"""
        html_path = self.output_dir / "client_report.html"

        summary = self.generate_executive_summary()
        current_date = datetime.now().strftime('%B %d, %Y')

        # Top opportunities table
        top_opportunities = [r for r in self.results if r['total_qualified_sections'] >= 4]

        opportunities_html = ""
        for i, opp in enumerate(top_opportunities[:10], 1):  # Top 10
            score_badge = f"""<span class="score-badge score-{opp['total_qualified_sections']}">{opp['total_qualified_sections']}/5</span>"""

            participants = ', '.join(opp['participants'][:3]) if opp['participants'] else 'N/A'
            if len(opp['participants']) > 3:
                participants += f" (+{len(opp['participants'])-3} more)"

            opportunities_html += f"""
            <tr>
                <td>{i}</td>
                <td><strong>{opp['title']}</strong></td>
                <td>{opp['date']}</td>
                <td>{participants}</td>
                <td>{score_badge}</td>
            </tr>
            """

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>UNKNOWN Brain - Analysis Results</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; }}
        .header h1 {{ margin: 0; font-size: 28px; }}
        .header p {{ margin: 10px 0 0 0; opacity: 0.9; }}
        .summary {{ background: #f8f9fa; padding: 25px; border-radius: 10px; margin-bottom: 30px; border-left: 4px solid #667eea; }}
        .summary h2 {{ margin-top: 0; color: #667eea; }}
        .summary ul {{ margin: 0; padding-left: 20px; }}
        .summary li {{ margin: 10px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }}
        th {{ background: #667eea; color: white; padding: 15px; text-align: left; font-weight: 600; }}
        td {{ padding: 12px 15px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f8f9fa; }}
        .score-badge {{ padding: 4px 8px; border-radius: 20px; font-weight: bold; color: white; font-size: 12px; }}
        .score-5 {{ background: #28a745; }}
        .score-4 {{ background: #ffc107; color: #000; }}
        .score-3 {{ background: #fd7e14; }}
        .score-2 {{ background: #dc3545; }}
        .score-1 {{ background: #6c757d; }}
        .footer {{ margin-top: 40px; padding: 20px; background: #f8f9fa; border-radius: 10px; text-align: center; color: #666; }}
        .note {{ background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #2196f3; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🧠 UNKNOWN Brain Analysis</h1>
        <p>Transcript Analysis Results - {current_date}</p>
    </div>

    <div class="summary">
        <h2>Executive Summary</h2>
{summary.replace('**', '<strong>').replace('**', '</strong>').replace('•', '<li>').replace(chr(10), '</li>' + chr(10)).replace('<li></li>', '')}
    </div>

    <h2>Top Opportunities</h2>
    <table>
        <thead>
            <tr>
                <th>Rank</th>
                <th>Meeting Title</th>
                <th>Date</th>
                <th>Participants</th>
                <th>Score</th>
            </tr>
        </thead>
        <tbody>
            {opportunities_html}
        </tbody>
    </table>

    <div class="note">
        <strong>Note:</strong> This analysis was generated using GPT-5-mini and evaluates meetings across 5 criteria:
        NOW (urgent needs), NEXT (future opportunities), MEASURE (clear metrics), BLOCKER (constraints), and FIT (alignment with UNKNOWN services).
        Meetings scoring 3/5 or higher are considered qualified opportunities.
    </div>

    <div class="footer">
        <p>Generated by UNKNOWN Brain AI Analysis System</p>
        <p>For detailed breakdown and evidence, see attached CSV file</p>
    </div>
</body>
</html>
        """

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return str(html_path)

    def generate_email_template(self) -> str:
        """Generate email template text"""
        email_path = self.output_dir / "email_template.txt"

        summary = self.generate_executive_summary()
        top_count = len([r for r in self.results if r['total_qualified_sections'] == 5])
        qualified_count = len([r for r in self.results if r['qualified']])
        current_time = datetime.now().strftime('%B %d, %Y at %I:%M %p')

        email_content = f"""Subject: UNKNOWN Brain Analysis Results - {qualified_count} Qualified Opportunities Identified

Hi [CLIENT_NAME],

I've completed the transcript analysis using our UNKNOWN Brain AI system. Here are the key findings:

{summary}

**Key Highlights:**
• {top_count} meetings show immediate high-value opportunities
• All qualified prospects include specific evidence and next steps
• Analysis covers hiring needs, growth opportunities, and service fit

**Next Steps:**
1. Review the attached detailed results (CSV format)
2. Prioritize follow-up with 5/5 scored prospects
3. Schedule strategy calls for qualified opportunities

The full analysis report is attached, including:
- Detailed scoring breakdown for each meeting
- Evidence snippets supporting each score
- Recommended follow-up actions

Let me know if you'd like to discuss any specific opportunities or need additional analysis.

Best regards,
[YOUR_NAME]

---
Generated by UNKNOWN Brain AI Analysis
{current_time}
"""

        with open(email_path, 'w', encoding='utf-8') as f:
            f.write(email_content)

        return str(email_path)

    def generate_all_reports(self):
        """Generate all report formats"""
        print("🔍 Extracting results from BigQuery...")
        results = self.extract_bq_results()

        if not results:
            print("❌ No results found")
            return

        print(f"✅ Found {len(results)} transcript results")

        print("📊 Generating CSV export...")
        csv_path = self.generate_detailed_csv()

        print("📄 Generating HTML report...")
        html_path = self.generate_html_report()

        print("📧 Generating email template...")
        email_path = self.generate_email_template()

        print(f"""
🎉 Client reports generated successfully!

Files created:
• HTML Report: {html_path}
• CSV Export: {csv_path}
• Email Template: {email_path}

Ready to share:
1. Send the HTML report as the main document
2. Attach the CSV for detailed analysis
3. Use the email template as your message
        """)

if __name__ == "__main__":
    generator = ClientReportGenerator()
    generator.generate_all_reports()