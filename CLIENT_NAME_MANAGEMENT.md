# Client Name Management Guide

This guide explains how UNKNOWN Brain handles client name extraction, deduplication, and normalization.

## Problem Summary

**Issues Identified:**
1. **Corrupted entries**: UUID fragments like `"Bcb88E78 88E8"` extracted from meeting IDs
2. **Duplicate variants**: Same client with different names (e.g., `"Omnicom"` vs `"Omnicom / DDB"`)
3. **Verbose LLM names**: Descriptive text in parentheses (e.g., `"Sophia (creative agency within Atoms & Space group)"`)

## Solution Architecture

### 1. Prevention (for new transcripts)

**File**: [src/llm_scorer.py](src/llm_scorer.py)

**Changes made:**
- UUID detection: Skip filename extraction for UUID-format meeting IDs
- Hex validation: Reject client names that are >80% hexadecimal characters
- Three-tier extraction: LLM → Filename → Domain heuristics

**How it works:**
```python
# Tier 1: LLM extraction (most accurate)
client_info = _extract_client_with_llm(transcript)

# Tier 2: Filename extraction (fallback)
# Now skips UUIDs and validates against hex garbage

# Tier 3: Domain heuristics (last resort)
# Falls back to "Unknown" if nothing found
```

### 2. Manual Mappings (for known variants)

**File**: [client_mappings.json](client_mappings.json)

**Purpose**: Define variant → canonical name mappings

**Example:**
```json
{
  "mappings": {
    "Legas Delaney": "Leagas Delaney",
    "Omnicom / DDB": "Omnicom",
    "Bcb88E78 88E8": "Unknown"
  }
}
```

**When to update:**
- New client name variants discovered
- LLM extracts same client with different formatting
- Manual overrides needed

### 3. CLI Commands (for data cleanup)

**List all clients:**
```bash
# Simple list
python -m src.cli list-clients

# With meeting counts
python -m src.cli list-clients --counts
```

**Fix corrupted/duplicate names:**
```bash
# Dry run (preview changes)
python -m src.cli fix-client-names

# Apply changes to BigQuery
python -m src.cli fix-client-names --execute

# Use custom mappings file
python -m src.cli fix-client-names --mappings custom.json --execute
```

### 4. BigQuery View (for normalized queries)

**File**: [sql/create_normalized_client_view.sql](sql/create_normalized_client_view.sql)

**Purpose**: Query-time normalization using CASE statements

**Usage:**
```sql
-- Create the view (run once)
-- (see sql/create_normalized_client_view.sql)

-- Query all meetings for a client (handles variants)
SELECT * FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel_normalized`
WHERE client_normalized = 'Omnicom'
ORDER BY date DESC;

-- Count meetings per normalized client
SELECT
  client_normalized,
  COUNT(*) as meeting_count,
  AVG(total_qualified_sections) as avg_score
FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel_normalized`
GROUP BY client_normalized
ORDER BY meeting_count DESC;
```

## Workflow for New Clients

### Scenario: New client appears in data

1. **Automatic extraction**: LLM extracts client name from transcript
2. **No action needed**: System now prevents corrupted entries
3. **Optional**: If LLM name is verbose, add mapping to `client_mappings.json`

### Scenario: Discover variant of existing client

1. **Identify variant**:
   ```bash
   python -m src.cli list-clients --counts
   ```

2. **Add to mappings**:
   Edit `client_mappings.json`:
   ```json
   {
     "mappings": {
       "New Variant Name": "Canonical Name"
     }
   }
   ```

3. **Preview fix**:
   ```bash
   python -m src.cli fix-client-names
   ```

4. **Apply fix**:
   ```bash
   python -m src.cli fix-client-names --execute
   ```

## Current Client List (41 unique names)

As of latest count:
- **Top clients by meetings**: BBDO Chicago (2), Brandfuel (2), Instrument (2), Media Arts Lab (2), Superside (2)
- **Known corrupted entries**: 3 (will be fixed to "Unknown")
- **Known duplicates**: 2 pairs (Leagas/Legas Delaney, Omnicom/Omnicom DDB)

Run `python -m src.cli list-clients --counts` for current state.

## Future Enhancements

### Option 1: Use client_id field
- Currently NULL for all records
- Could manually assign IDs for canonical linking
- Preserves original LLM-extracted names

### Option 2: Fuzzy matching
- Implement Levenshtein distance for auto-detection
- Suggest similar clients when querying
- Semi-automated deduplication

### Option 3: Master data management
- External client database
- API lookup during scoring
- Centralized source of truth

## Technical Details

### client_info Schema (BigQuery JSON field)

```json
{
  "client_id": null,              // Reserved for future linking
  "client": "Company Name",       // LLM-extracted name
  "domain": "industry vertical",  // Business sector
  "size": "startup|scaleup|enterprise",
  "source": "llm|filename|domain" // Extraction method
}
```

### Querying client_info

```sql
-- Extract client name
SELECT JSON_VALUE(client_info, '$.client') as client
FROM meeting_intel;

-- Filter by extraction source
WHERE JSON_VALUE(client_info, '$.source') = 'llm';

-- Update client name
UPDATE meeting_intel
SET client_info = JSON_SET(client_info, '$.client', 'New Name')
WHERE meeting_id = 'xxx';
```

## Maintenance

### Monthly review checklist
- [ ] Run `list-clients --counts` to identify new variants
- [ ] Update `client_mappings.json` with discovered duplicates
- [ ] Run `fix-client-names --execute` to apply fixes
- [ ] Review BigQuery view CASE statements (if needed)

### When re-scoring transcripts
- Corrupted entries will be automatically prevented
- Existing mappings won't be lost
- May discover new variants from LLM improvements
