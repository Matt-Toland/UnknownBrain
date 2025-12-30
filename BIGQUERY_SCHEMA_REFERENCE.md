# BigQuery Schema Reference - Meeting Intelligence Table

## Table: `angular-stacker-471711-k4.unknown_brain.meeting_intel`

Complete reference for all fields available for querying in weekly insights and coaching emails.

---

## 📋 CORE MEETING METADATA

### `meeting_id` (STRING)
- **Description**: Unique identifier for each meeting
- **Example**: `"c2312e51-8a7b-4c15-9c20-cae15aa7d367"`
- **Use Case**: Primary key, linking records across systems
- **Queryable**: Yes
- **Nullable**: No

### `date` (DATE)
- **Description**: Date the meeting occurred
- **Example**: `2025-12-17`
- **Use Case**: Time-series analysis, weekly/monthly reporting, trend analysis
- **Queryable**: Yes - Use for filtering by date range
- **SQL Example**: `WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)`

### `title` (STRING)
- **Description**: Meeting subject/title
- **Example**: `"Client Discovery - Acme Corp"`
- **Use Case**: Meeting identification, categorization
- **Queryable**: Yes

### `participants` (ARRAY<STRING>)
- **Description**: Array of participant names, **first participant is always the salesperson**
- **Example**: `["Sam", "Client Name", "Client Name 2"]`
- **Use Case**: Identifying who attended, team collaboration analysis
- **Queryable**: Yes
- **SQL Example**: `WHERE 'Sam' IN UNNEST(participants)`
- **Note**: First element is used to populate `salesperson_name`

### `salesperson_name` (STRING)
- **Description**: Name of the UNKNOWN salesperson leading the meeting (extracted from first participant)
- **Example**: `"Sam"`, `"Ollie"`, `"Sean"`
- **Use Case**: Individual performance tracking, team comparisons, coaching reports
- **Queryable**: Yes - **Primary field for individual reporting**
- **SQL Example**: `WHERE salesperson_name = 'Sam'`
- **Values**: Sam, Ollie, Sean, Ellie, Sam Winward, Woody, Ollie Scott, Richard, Molly, Ellie Gould

### `desk` (STRING)
- **Description**: Client company/organization name
- **Example**: `"Acme Corp"`, `"Unknown"`
- **Use Case**: Client-level analysis, deal tracking
- **Queryable**: Yes
- **Note**: Often "Unknown" if not specified

### `source` (STRING)
- **Description**: Origin of the meeting data
- **Example**: `"granola"`, `"bigquery"`, `"manual"`
- **Use Case**: Data quality tracking, source attribution
- **Queryable**: Yes

### `scored_at` (TIMESTAMP)
- **Description**: When the meeting was scored by the LLM
- **Example**: `2025-12-17 14:30:45 UTC`
- **Use Case**: Tracking when assessments were generated, data freshness
- **Queryable**: Yes
- **SQL Example**: `WHERE scored_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)`

### `llm_model` (STRING)
- **Description**: Which AI model was used for scoring
- **Example**: `"gpt-5-mini"`, `"gpt-4o-mini"`
- **Use Case**: Model performance comparison, audit trail
- **Queryable**: Yes

---

## 🎯 OPPORTUNITY SCORING (Analyzes "Them:" - The Client)

These fields assess whether the client is a good opportunity for UNKNOWN:

### `total_qualified_sections` (INTEGER)
- **Description**: Count of opportunity criteria met (0-5)
- **Range**: 0 to 5
- **Threshold**: ≥3 = Qualified opportunity
- **Use Case**: Filtering qualified leads, pipeline quality
- **SQL Example**: `WHERE total_qualified_sections >= 3`

### `now` (JSON)
- **Description**: Urgent hiring needs within 60 days
- **Structure**:
  ```json
  {
    "qualified": true,
    "score": 1,
    "evidence_line": "Need to hire 3 designers by end of Q1...",
    "timestamp": null
  }
  ```
- **Fields**:
  - `qualified` (BOOLEAN): Met threshold (score = 1)
  - `score` (INTEGER): 0 or 1
  - `evidence_line` (STRING): Supporting quote from transcript
- **Use Case**: Identifying hot leads, urgency scoring
- **SQL Example**: `WHERE JSON_EXTRACT_SCALAR(now, '$.qualified') = 'true'`

### `next` (JSON)
- **Description**: Future opportunities (60-180 days)
- **Structure**: Same as `now`
- **Use Case**: Pipeline building, future opportunity tracking

### `measure` (JSON)
- **Description**: Clear success metrics/KPIs mentioned
- **Structure**: Same as `now`
- **Use Case**: Identifying data-driven clients, goal alignment

### `blocker` (JSON)
- **Description**: Explicit obstacles or constraints
- **Structure**: Same as `now`
- **Use Case**: Risk assessment, identifying challenges to address

### `fit` (JSON)
- **Description**: Match with UNKNOWN services (Talent/Evolve/Ventures)
- **Structure**: Same as `now` plus:
  ```json
  {
    "qualified": true,
    "score": 1,
    "evidence_line": "...",
    "fit_labels": ["Access", "Transform", "Ventures"]
  }
  ```
- **Use Case**: Service line allocation, capability matching

### Taxonomy Fields (Client Context)
- `challenges` (ARRAY<STRING>): Client pain points identified
- `results` (ARRAY<STRING>): Desired outcomes mentioned
- `offering` (STRING): Relevant UNKNOWN service line

---

## 💼 SALES ASSESSMENT (Analyzes "Me:" - The Salesperson)

These fields assess the salesperson's performance in the meeting:

### `sales_total_score` (INTEGER)
- **Description**: Total sales performance score across all 8 criteria
- **Range**: 0 to 24 (8 criteria × 3 points each)
- **Use Case**: Overall performance ranking, improvement tracking
- **Benchmarks**:
  - 21-24: Excellent
  - 16-20: Strong
  - 11-15: Developing
  - 6-10: Needs Improvement
  - 0-5: Critical
- **Team Average**: 14.1/24 (59%)
- **SQL Example**: `WHERE sales_total_score >= 16` (Strong performers only)

### `sales_total_qualified` (INTEGER)
- **Description**: Count of criteria scoring ≥2 (out of 8)
- **Range**: 0 to 8
- **Threshold**: ≥5 = Qualified sales performance
- **Use Case**: Quick competency check, baseline performance filter

### `sales_qualified` (BOOLEAN)
- **Description**: Met minimum performance threshold (≥5 criteria at 2+)
- **Use Case**: Binary pass/fail for performance gates
- **SQL Example**: `WHERE sales_qualified = true`

### `sales_performance_rating` (STRING)
- **Description**: Performance tier based on total score
- **Values**:
  - "Excellent" (21-24)
  - "Strong" (16-20)
  - "Developing" (11-15)
  - "Needs Improvement" (6-10)
  - "Significant Development Needed" (0-5)
- **Use Case**: Human-readable performance categories for reporting
- **SQL Example**: `WHERE sales_performance_rating = 'Developing'`

---

## 📊 INDIVIDUAL SALES CRITERIA (JSON Fields)

Each criterion is scored 0-3 and stored as JSON:

**Score Scale**:
- **0**: Not demonstrated at all
- **1**: Basic attempt but missing key elements
- **2**: Adequate execution with room to improve
- **3**: Excellence/Mastery

**JSON Structure** (all criteria follow this format):
```json
{
  "qualified": boolean,        // true if score >= 2
  "score": integer,           // 0, 1, 2, or 3
  "reason": string,           // Detailed explanation of score
  "evidence": string,         // Supporting quote from transcript (may be null)
  "coaching_note": string     // Specific improvement advice
}
```

### 1. `sales_introduction` (JSON)
- **What It Measures**: Meeting setup, agenda setting, rapport building
- **Excellence Looks Like**: Clear intro, structured agenda, permission to probe
- **Common Gap**: Skipping agenda or not asking permission to challenge
- **Team Average**: 1.64/3
- **SQL Example**:
  ```sql
  WHERE CAST(JSON_EXTRACT_SCALAR(sales_introduction, '$.score') AS INT64) >= 2
  ```

### 2. `sales_discovery` (JSON)
- **What It Measures**: Questioning quality, uncovering needs, active listening
- **Excellence Looks Like**: Open-ended questions, layered follow-ups, probing impact and emotions
- **Common Gap**: Surface-level questions without digging deeper
- **Team Average**: 1.82/3 ⭐ (Strongest area)

### 3. `sales_scoping` (JSON)
- **What It Measures**: Qualifying budget, timeline, stakeholders, decision process
- **Excellence Looks Like**: Direct questions about money, authority, need, timing (MANT)
- **Common Gap**: Avoiding budget/authority conversations
- **Team Average**: 1.00/3

### 4. `sales_solution` (JSON)
- **What It Measures**: Product positioning, value articulation, tailored recommendations
- **Excellence Looks Like**: Mapping client pain to specific products with outcomes
- **Common Gap**: Generic pitching vs. consulting approach
- **Team Average**: 1.55/3

### 5. `sales_commercial` (JSON)
- **What It Measures**: Fee discussion, commercial confidence, value justification
- **Excellence Looks Like**: Stating fees confidently early, explaining value, checking budget fit
- **Common Gap**: Avoiding or delaying fee discussion
- **Team Average**: 0.82/3 ⚠️ (Weakest area)

### 6. `sales_case_studies` (JSON)
- **What It Measures**: Sharing proof points, relevant examples, storytelling
- **Excellence Looks Like**: 2-3 relevant client stories with metrics and outcomes
- **Common Gap**: Not preparing or sharing case studies
- **Team Average**: 0.82/3 ⚠️ (Weakest area)

### 7. `sales_next_steps` (JSON)
- **What It Measures**: Securing commitments, clear follow-ups, meeting closure
- **Excellence Looks Like**: Specific date/time, agreed actions, identified decision-makers
- **Common Gap**: Vague "let's chat soon" vs. booked calendar invite
- **Team Average**: 0.82/3 ⚠️ (Weakest area)

### 8. `sales_strategic_context` (JSON)
- **What It Measures**: Understanding bigger picture, org design, future state
- **Excellence Looks Like**: Asking about 12-month vision, strategic priorities, change drivers
- **Common Gap**: Staying tactical vs. strategic
- **Team Average**: 1.64/3

---

## 🎯 AGGREGATED SALES INSIGHTS

### `sales_strengths` (ARRAY<STRING>)
- **Description**: List of criteria where salesperson scored 3/3 (excellence)
- **Format**: `["Criterion Name: Coaching note explaining what they did well"]`
- **Example**:
  ```json
  [
    "Commercial Confidence: Rep stated fees clearly in first 10 minutes, justified value, and checked budget alignment",
    "Next Steps: Secured specific follow-up meeting with date/time and confirmed stakeholders"
  ]
  ```
- **Use Case**: Highlighting best practices, positive feedback, peer learning
- **Note**: Empty array `[]` if no 3/3 scores (most common)
- **SQL Example**:
  ```sql
  WHERE ARRAY_LENGTH(sales_strengths) > 0  -- Has at least one strength
  ```

### `sales_improvements` (ARRAY<STRING>)
- **Description**: Top 3 criteria needing work (lowest scores with coaching notes)
- **Format**: Same as `sales_strengths`
- **Example**:
  ```json
  [
    "Commercial Confidence: Practice stating fees confidently in first 15 mins",
    "Case Studies: Prepare 3 relevant client stories before each meeting",
    "Next Steps: Always book specific follow-up date before ending call"
  ]
  ```
- **Use Case**: Coaching priorities, development plans, skill gap identification
- **Always Populated**: Yes (every meeting has improvement areas)

### `sales_overall_coaching` (STRING)
- **Description**: High-level coaching recommendation based on total score
- **Values**:
  - "Excellent performance. Keep refining and share best practices."
  - "Strong performance. Focus on consistency across all meetings."
  - "Developing well. Focus on mastering the fundamentals."
  - "Needs focused coaching. Review basics with manager."
  - "Significant coaching opportunity. Consider shadowing senior reps."
- **Use Case**: Executive summary, intervention prioritization

---

## 📈 WEEKLY INSIGHTS SQL QUERY EXAMPLES

### Example 1: Last Week's Team Performance
```sql
SELECT
  salesperson_name,
  COUNT(*) as meetings,
  AVG(sales_total_score) as avg_score,
  AVG(total_qualified_sections) as avg_opportunity_score,
  COUNTIF(sales_qualified) as qualified_meetings,
  COUNTIF(total_qualified_sections >= 3) as qualified_opportunities
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND sales_total_score IS NOT NULL
GROUP BY salesperson_name
ORDER BY avg_score DESC
```

### Example 2: Top Performers This Week
```sql
SELECT
  salesperson_name,
  date,
  sales_total_score,
  sales_strengths,
  desk as client
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND sales_total_score >= 16  -- Strong performance
ORDER BY sales_total_score DESC
LIMIT 3
```

### Example 3: Coaching Priorities by Individual
```sql
SELECT
  salesperson_name,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS FLOAT64)) as commercial_avg,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_case_studies, '$.score') AS FLOAT64)) as case_studies_avg,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_next_steps, '$.score') AS FLOAT64)) as next_steps_avg,
  COUNT(*) as meetings
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND sales_total_score IS NOT NULL
GROUP BY salesperson_name
ORDER BY salesperson_name
```

### Example 4: Weekly Improvement Trends
```sql
WITH weekly_scores AS (
  SELECT
    salesperson_name,
    DATE_TRUNC(date, WEEK) as week,
    AVG(sales_total_score) as avg_score
  FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
  WHERE sales_total_score IS NOT NULL
  GROUP BY salesperson_name, week
)
SELECT
  salesperson_name,
  week,
  avg_score,
  LAG(avg_score) OVER (PARTITION BY salesperson_name ORDER BY week) as prev_week_score,
  avg_score - LAG(avg_score) OVER (PARTITION BY salesperson_name ORDER BY week) as improvement
FROM weekly_scores
ORDER BY salesperson_name, week DESC
```

### Example 5: Skill Gap Heatmap
```sql
SELECT
  'Introduction' as criterion,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_introduction, '$.score') AS FLOAT64)) as team_avg,
  MIN(CAST(JSON_EXTRACT_SCALAR(sales_introduction, '$.score') AS FLOAT64)) as min_score,
  MAX(CAST(JSON_EXTRACT_SCALAR(sales_introduction, '$.score') AS FLOAT64)) as max_score,
  COUNTIF(CAST(JSON_EXTRACT_SCALAR(sales_introduction, '$.score') AS INT64) >= 2) * 100.0 / COUNT(*) as pct_qualified
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE sales_total_score IS NOT NULL
  AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

UNION ALL

SELECT
  'Commercial' as criterion,
  AVG(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS FLOAT64)),
  MIN(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS FLOAT64)),
  MAX(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS FLOAT64)),
  COUNTIF(CAST(JSON_EXTRACT_SCALAR(sales_commercial, '$.score') AS INT64) >= 2) * 100.0 / COUNT(*)
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE sales_total_score IS NOT NULL
  AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

-- Add similar UNION ALL for other 6 criteria
ORDER BY team_avg ASC
```

### Example 6: Individual Coaching Report Data
```sql
-- Pull all data needed for Sam's weekly coaching email
SELECT
  meeting_id,
  date,
  desk as client,
  sales_total_score,
  sales_performance_rating,
  sales_strengths,
  sales_improvements,
  sales_overall_coaching,
  -- Individual criterion scores
  JSON_EXTRACT_SCALAR(sales_introduction, '$.score') as intro_score,
  JSON_EXTRACT_SCALAR(sales_discovery, '$.score') as discovery_score,
  JSON_EXTRACT_SCALAR(sales_commercial, '$.score') as commercial_score,
  JSON_EXTRACT_SCALAR(sales_case_studies, '$.score') as case_studies_score,
  JSON_EXTRACT_SCALAR(sales_next_steps, '$.score') as next_steps_score,
  -- Coaching notes for each
  JSON_EXTRACT_SCALAR(sales_commercial, '$.coaching_note') as commercial_coaching,
  JSON_EXTRACT_SCALAR(sales_case_studies, '$.coaching_note') as case_studies_coaching,
  JSON_EXTRACT_SCALAR(sales_next_steps, '$.coaching_note') as next_steps_coaching
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE salesperson_name = 'Sam'
  AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND sales_total_score IS NOT NULL
ORDER BY date DESC
```

---

## 🎨 EMAIL TEMPLATE DATA STRUCTURE

For generating weekly insights emails, you can structure data like this:

```json
{
  "week_ending": "2025-12-17",
  "team_summary": {
    "total_meetings": 15,
    "avg_score": 14.2,
    "qualified_rate": 73,
    "top_performer": "Woody",
    "most_improved": "Sam (+2.3 points)"
  },
  "individual_reports": [
    {
      "salesperson": "Sam",
      "meetings": 4,
      "avg_score": 15.5,
      "trend": "↑ +1.2",
      "strengths": ["Discovery", "Strategic Context"],
      "improvements": ["Commercial", "Next Steps"],
      "priority_action": "Practice stating fees in first 15 mins"
    }
  ],
  "team_insights": {
    "critical_gap": "Commercial Confidence (0.82/3)",
    "best_practice": "Woody's fee discussion approach",
    "upcoming_training": "Commercial Confidence Bootcamp"
  }
}
```

---

## 📌 QUICK REFERENCE: Key Fields for Coaching Emails

**For Team-Wide Reports:**
- `salesperson_name` - Who
- `date` - When
- `sales_total_score` - Overall performance
- `sales_performance_rating` - Category
- `sales_strengths` - What's working
- `sales_improvements` - What needs work

**For Individual Coaching:**
- All 8 `sales_*` criterion JSONs for detailed feedback
- `sales_overall_coaching` for summary
- Compare to team averages for context

**For Leadership Dashboard:**
- `sales_total_score` distribution
- Trend analysis over time
- Qualification rates (`sales_qualified`)
- ROI: Correlate `sales_total_score` with `total_qualified_sections`