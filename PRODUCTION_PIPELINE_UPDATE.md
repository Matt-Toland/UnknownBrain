# Production Pipeline Update for Sales Assessment

## How to Integrate Sales Assessment into Automated Cloud Run Pipeline

### 1. **Update Default CLI Command**
In your Cloud Run service or wherever you call the scoring command, change from:
```bash
python -m src.cli score --bq-export
```

To:
```bash
python -m src.cli score --bq-export --include-sales-assessment
```

### 2. **Update main.py or Entry Point**
If you have a main.py that runs the scoring, update it:

```python
# Before
from src.cli import score
score(bq_export=True)

# After
from src.cli import score
score(bq_export=True, include_sales_assessment=True)
```

### 3. **Environment Variable Approach (Recommended)**
Add an environment variable to control sales assessment:

```python
# In your scoring script
import os

include_sales = os.getenv('ENABLE_SALES_ASSESSMENT', 'true').lower() == 'true'

if include_sales:
    result = score(
        bq_export=True,
        include_sales_assessment=True
    )
else:
    result = score(bq_export=True)
```

Then set in Cloud Run:
```yaml
env:
  - name: ENABLE_SALES_ASSESSMENT
    value: "true"
```

### 4. **Update BigQuery Post-Processing**
Add a post-processing step to ensure salesperson names are populated:

```python
def post_process_bigquery():
    """Update NULL salesperson names after scoring."""
    from google.cloud import bigquery

    client = bigquery.Client()

    # Update NULL salesperson names with first participant
    query = """
    UPDATE `angular-stacker-471711-k4.unknown_brain.meeting_intel`
    SET salesperson_name = participants[SAFE_OFFSET(0)]
    WHERE salesperson_name IS NULL
      AND ARRAY_LENGTH(participants) > 0
    """

    job = client.query(query)
    job.result()
    print(f"Updated {job.num_dml_affected_rows} salesperson names")
```

### 5. **Dockerfile Update (if using Docker)**
No changes needed to Dockerfile, but ensure requirements.txt is current.

### 6. **Cloud Run Deployment Script**
Update your deployment script:

```bash
#!/bin/bash

# Build and push with sales assessment enabled
gcloud builds submit --tag gcr.io/YOUR_PROJECT/unknown-brain

# Deploy with environment variable
gcloud run deploy unknown-brain \
  --image gcr.io/YOUR_PROJECT/unknown-brain \
  --set-env-vars ENABLE_SALES_ASSESSMENT=true \
  --memory 2Gi \
  --timeout 3600
```

### 7. **Scheduled Cloud Function/Scheduler Update**
If using Cloud Scheduler, update the job:

```bash
gcloud scheduler jobs update http score-meetings \
  --message-body='{"include_sales_assessment": true}'
```

### 8. **Testing Before Deployment**
Test locally with a single meeting:

```bash
# Test with sales assessment
python -m src.cli score \
  --include-sales-assessment \
  --in data/test \
  --out out/test \
  --model gpt-5-mini

# Verify all fields are populated
python -c "
import json
with open('out/test/bq_export.jsonl') as f:
    data = json.loads(f.readline())
    print('Sales fields present:', 'sales_total_score' in data)
    print('Sales score:', data.get('sales_total_score'))
"
```

## Key Changes in the Codebase

### Files Modified:
1. `src/schemas.py` - Added sales assessment models
2. `src/llm_scorer.py` - Added `score_salesperson()` method
3. `src/bq_loader.py` - Added 15 new BigQuery columns
4. `src/cli.py` - Added `--include-sales-assessment` flag
5. `src/scoring.py` - Updated to handle sales fields

### BigQuery Schema Changes:
- 15 new columns added (sales_* fields)
- All are nullable to maintain backward compatibility
- MERGE strategy prevents duplicates

## Deployment Checklist

- [ ] Test scoring with `--include-sales-assessment` locally
- [ ] Verify BigQuery schema has all sales columns
- [ ] Update Cloud Run environment variables
- [ ] Update any scheduled jobs or triggers
- [ ] Deploy new code to Cloud Run
- [ ] Monitor first automated run for errors
- [ ] Verify sales fields are populated in BigQuery

## Rollback Plan

If issues occur, you can disable sales assessment without rolling back code:

1. Set environment variable: `ENABLE_SALES_ASSESSMENT=false`
2. Or remove `--include-sales-assessment` flag from commands
3. Sales columns will remain NULL but won't break existing pipeline

## Performance Considerations

- Sales assessment adds ~8 API calls per meeting
- Increases processing time by ~2x
- Consider batching if processing many meetings
- Monitor OpenAI API rate limits

## Monitoring

After deployment, check:
```sql
-- Verify sales assessments are being created
SELECT
  DATE(scored_at) as date,
  COUNT(*) as meetings_scored,
  AVG(sales_total_score) as avg_score,
  COUNTIF(sales_total_score IS NULL) as missing_scores
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
WHERE scored_at >= CURRENT_DATE()
GROUP BY date
ORDER BY date DESC;
```