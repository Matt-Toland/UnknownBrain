# Sales Assessment API Integration Guide

## Overview
We've added 8 new sales assessment criteria to the UNKNOWN Brain scoring system. These assess the salesperson's performance (analyzing "Me:" speakers) separately from opportunity scoring (analyzing "Them:" speakers). You'll need to build a new endpoint specifically for individual sales coaching reports.

## New BigQuery Schema Columns

### Summary Columns
- `sales_total_score` (INTEGER): Total score across all 8 criteria (0-24)
- `sales_total_qualified` (INTEGER): Count of criteria scoring 2+ out of 3 (0-8)
- `sales_qualified` (BOOLEAN): True if sales_total_qualified >= 5
- `sales_performance_rating` (STRING): Performance level based on total score
  - "Excellent" (21-24)
  - "Strong" (16-20)
  - "Developing" (11-15)
  - "Needs Improvement" (6-10)
  - "Significant Development Needed" (0-5)
- `salesperson_name` (STRING): Extracted name of the salesperson

### Individual Criterion Columns (JSON format)
Each of these contains a JSON object with the assessment details:

1. `sales_introduction` - Meeting setup and agenda setting
2. `sales_discovery` - Questioning and uncovering needs
3. `sales_scoping` - Qualifying budget, timeline, stakeholders
4. `sales_solution` - Positioning products/services
5. `sales_commercial` - Discussing fees and commercial terms
6. `sales_case_studies` - Sharing relevant proof points
7. `sales_next_steps` - Securing commitments and follow-ups
8. `sales_strategic_context` - Understanding broader business context

### JSON Object Structure
Each criterion column contains:
```json
{
  "qualified": boolean,  // true if score >= 2
  "score": integer,      // 0-3 scale
  "reason": string,      // Detailed explanation of score
  "evidence": string,    // Quote from transcript (may be null)
  "coaching_note": string // Specific improvement advice
}
```

### Aggregate Columns
- `sales_strengths` (JSON ARRAY): List of criteria scoring 3/3
  - Format: `["Introduction: <coaching note>", "Discovery: <coaching note>"]`
  - Empty array if no 3/3 scores

- `sales_improvements` (JSON ARRAY): Top 3 criteria needing work (lowest scores)
  - Format: `["Commercial Confidence: <coaching note>", ...]`

- `sales_overall_coaching` (STRING): High-level coaching recommendation
  - "Excellent performance. Keep refining and share best practices."
  - "Strong performance. Focus on consistency."
  - "Developing well. Focus on fundamentals."
  - "Needs focused coaching. Review basics."
  - "Significant coaching opportunity. Consider shadowing."

## Scoring Scale Interpretation

### Per Criterion (0-3 scale):
- **0**: Not demonstrated at all
- **1**: Basic attempt but missing key elements
- **2**: Adequate execution with room to improve
- **3**: Excellent execution demonstrating mastery

### Example Score Interpretation:
```json
{
  "sales_commercial": {
    "qualified": false,
    "score": 1,
    "reason": "The rep mentioned services but avoided discussing fees, payment terms, or budget alignment. No commercial confidence demonstrated.",
    "evidence": "Me: 'We can definitely help with that...' [no fee discussion]",
    "coaching_note": "Next time, state fees confidently: 'Our Partnership model is £X/month which includes Y. Does that align with your budget?'"
  }
}
```

## New Endpoint Requirements

### Endpoint: `/api/sales-coaching/{salesperson_name}`

### Response Format:
```json
{
  "salesperson": "Ollie",
  "period": "Last 30 days",
  "meetings_count": 5,
  "average_score": 15.2,
  "performance_trend": "improving",  // or "declining", "stable"

  "strengths": [
    {
      "criterion": "Discovery",
      "frequency": "80%",  // % of meetings scoring 2+
      "example": "Consistently asks probing questions about business impact"
    }
  ],

  "development_areas": [
    {
      "criterion": "Commercial Confidence",
      "average_score": 0.8,
      "specific_feedback": "Avoided fee discussions in 4 of 5 meetings",
      "action_item": "Practice stating fees in first 15 minutes"
    }
  ],

  "recent_meetings": [
    {
      "meeting_id": "xxx",
      "date": "2024-12-01",
      "client": "Company X",
      "score": 18,
      "key_win": "Secured clear next steps with timeline",
      "key_miss": "No case studies shared"
    }
  ],

  "coaching_priorities": [
    "1. Build commercial confidence - state fees early and clearly",
    "2. Prepare 3 relevant case studies for each meeting",
    "3. Always end with specific dated next steps"
  ]
}
```

## SQL Query Examples

### Get individual salesperson performance:
```sql
SELECT
  salesperson_name,
  COUNT(*) as meetings,
  AVG(sales_total_score) as avg_score,

  -- Extract individual criterion scores
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_introduction, '$.score') AS FLOAT64)) as avg_intro,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_discovery, '$.score') AS FLOAT64)) as avg_discovery,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS FLOAT64)) as avg_commercial,

  -- Count strong performances
  COUNTIF(CAST(JSON_EXTRACT_SCALAR(sales_discovery, '$.score') AS INT64) >= 2) as good_discoveries,

  -- Get most recent performance
  ARRAY_AGG(
    STRUCT(date, client, sales_total_score)
    ORDER BY date DESC
    LIMIT 5
  ) as recent_meetings

FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE salesperson_name = 'Ollie'
  AND sales_total_score IS NOT NULL
  AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY salesperson_name
```

### Get coaching priorities across team:
```sql
WITH criterion_scores AS (
  SELECT
    salesperson_name,
    AVG(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS FLOAT64)) as commercial_avg,
    AVG(CAST(JSON_EXTRACT_SCALAR(sales_case_studies, '$.score') AS FLOAT64)) as case_studies_avg,
    AVG(CAST(JSON_EXTRACT_SCALAR(sales_next_steps, '$.score') AS FLOAT64)) as next_steps_avg
  FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
  WHERE sales_total_score IS NOT NULL
  GROUP BY salesperson_name
)
SELECT
  salesperson_name,
  LEAST(commercial_avg, case_studies_avg, next_steps_avg) as weakest_area_score,
  CASE
    WHEN commercial_avg = LEAST(commercial_avg, case_studies_avg, next_steps_avg) THEN 'Commercial'
    WHEN case_studies_avg = LEAST(commercial_avg, case_studies_avg, next_steps_avg) THEN 'Case Studies'
    ELSE 'Next Steps'
  END as primary_development_area
FROM criterion_scores
ORDER BY weakest_area_score ASC
```

## Implementation Notes

1. **Performance Ratings**: Use sales_performance_rating for quick categorization
2. **Coaching Focus**: Prioritize criteria scoring < 2 (not qualified)
3. **Trend Analysis**: Compare average scores across time periods
4. **Team Benchmarking**: Compare individual averages to team averages
5. **Empty Values**: Some meetings may not have sales assessments (sales_total_score = NULL)
6. **Evidence Quotes**: May be null for some criteria, especially when score = 0

## Current Performance Baseline (from 11 scored meetings)
- Average total score: 10.1/24 (42%)
- No criteria have achieved 3/3 excellence yet
- Weakest areas: Commercial (0.82/3), Case Studies (0.82/3), Next Steps (0.82/3)
- Strongest areas: Discovery (1.82/3), Introduction (1.64/3)
- Top performer: Ollie with 15/24

## Key Differences from Opportunity Scoring
- **Opportunity scores** (NOW, NEXT, MEASURE, BLOCKER, FIT) are binary (0 or 1)
- **Sales assessment scores** are granular (0, 1, 2, or 3)
- **Opportunity** analyzes client readiness ("Them:" speakers)
- **Sales assessment** analyzes rep performance ("Me:" speakers)
- Both systems run independently and have separate qualification thresholds

## Testing the New Endpoint
Focus on:
1. Salesperson with multiple meetings (e.g., "Ollie", "Sam", "Sean")
2. Time-based trending (weekly/monthly performance changes)
3. Criterion-specific drill-downs (which areas need most work)
4. Actionable coaching recommendations based on evidence
5. Comparative performance (individual vs team average)