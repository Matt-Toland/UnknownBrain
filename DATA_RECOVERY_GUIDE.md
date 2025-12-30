# Data Recovery Guide - Text Fields in BigQuery

## Issue Summary
When we exported meetings for sales scoring and re-uploaded them via MERGE, the `enhanced_notes`, `full_transcript`, and `my_notes` fields were overwritten with NULL values because these fields weren't included in the scoring output.

## Root Cause
The MERGE operation in `src/bq_loader.py` was updating ALL fields when matching on meeting_id, including setting text fields to NULL when they weren't present in the upload data.

## Recovery Process

### Step 1: Generate Recovery SQL
```bash
python generate_recovery_sql.py
```
This creates `recovery_updates.sql` containing UPDATE statements to restore text fields from local JSON backups.

### Step 2: Execute Recovery
```bash
# Review the SQL first
head -50 recovery_updates.sql

# Execute all updates
bq query --use_legacy_sql=false < recovery_updates.sql

# Or execute in smaller batches
head -200 recovery_updates.sql | bq query --use_legacy_sql=false
```

### Step 3: Verify Recovery
```bash
bq query --use_legacy_sql=false "
SELECT
    COUNT(*) as total_rows,
    COUNTIF(enhanced_notes IS NULL) as null_enhanced,
    COUNTIF(full_transcript IS NULL) as null_transcript,
    COUNTIF(sales_total_score IS NOT NULL) as has_sales_score
FROM \`fifth-sprite-167216.unknown_2024.meeting_intel\`
"
```

## Prevention - COALESCE Fix

The MERGE statement in `src/bq_loader.py` has been updated to use COALESCE, which preserves existing non-NULL values:

```sql
-- Old (problematic) approach:
enhanced_notes = source.enhanced_notes,

-- New (safe) approach:
enhanced_notes = COALESCE(source.enhanced_notes, target.enhanced_notes),
```

This ensures that if the source value is NULL, the existing target value is preserved.

## Available Recovery Scripts

1. **generate_recovery_sql.py** - Scans local JSON files and generates SQL UPDATE statements
2. **recover_text_fields.py** - Direct BigQuery recovery (requires proper auth)

## Data Sources for Recovery

Recovery data can be found in:
- `data/json_backfill/` - 10 files
- `data/json_batch2/` - 83 files
- `data/json_batch4-9/` - Various batch directories
- `data/json_staging/` - 73 files

Total: ~363 JSON files with recoverable text data

## Lessons Learned

1. **Always preserve existing data**: Use COALESCE in MERGE operations when dealing with partial updates
2. **Include all fields in exports**: Even if not needed for processing, include them to avoid data loss
3. **Test with small batches first**: Always test data operations on a few records before bulk operations
4. **Create backups**: Before any major data operation, create a backup table

## Emergency Recovery Commands

If you need to restore from a backup table:
```bash
# Create backup (always do this first!)
bq cp fifth-sprite-167216:unknown_2024.meeting_intel \
      fifth-sprite-167216:unknown_2024.meeting_intel_backup_$(date +%Y%m%d)

# Restore from backup
bq cp --force \
      fifth-sprite-167216:unknown_2024.meeting_intel_backup_20251229 \
      fifth-sprite-167216:unknown_2024.meeting_intel
```