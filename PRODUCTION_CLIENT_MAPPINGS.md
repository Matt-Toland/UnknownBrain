# Production Client Name Mappings Guide

## Overview

Client name mappings are now stored in **BigQuery** instead of a JSON file, making them persistent across Cloud Run deployments and editable without redeploying.

## Quick Start

### Initialize mappings table (one-time setup)

```bash
# Import existing mappings from client_mappings.json
python -m src.cli init-mappings

# Or create empty table
python -m src.cli init-mappings --empty
```

### View current mappings

```bash
python -m src.cli list-mappings
```

### Add a new mapping

```bash
# Basic
python -m src.cli add-client-mapping "Legas Delaney" "Leagas Delaney"

# With notes
python -m src.cli add-client-mapping "Omnicom / DDB" "Omnicom" --notes "Normalize to parent company"
```

### Delete a mapping

```bash
python -m src.cli delete-client-mapping "Old Variant Name"
```

### Fix client names in BigQuery

```bash
# Preview changes (dry run)
python -m src.cli fix-client-names

# Apply changes
python -m src.cli fix-client-names --execute

# Use JSON file instead of BigQuery table (legacy)
python -m src.cli fix-client-names --use-file --execute
```

## Production Workflow

### On Cloud Run (automatic)

1. **Scoring runs** → `llm_scorer.py` prevents corrupted names
2. **Upload runs** → Client names stored as-is in `meeting_intel` table
3. **Query time** → Use `fix-client-names` command or BigQuery view for normalization

### Adding new mappings (no redeployment needed!)

```bash
# Discover variant
python -m src.cli list-clients --counts

# Add mapping via CLI (updates BigQuery immediately)
python -m src.cli add-client-mapping "New Variant" "Canonical Name"

# Apply fix to existing records
python -m src.cli fix-client-names --execute
```

## BigQuery Table Schema

```sql
CREATE TABLE `angular-stacker-471711-k4.unknown_brain.client_mappings` (
  variant_name STRING NOT NULL,      -- Variant client name
  canonical_name STRING NOT NULL,     -- Canonical name to use
  notes STRING,                       -- Optional notes
  created_at TIMESTAMP,              -- When mapping was created
  updated_at TIMESTAMP               -- When mapping was last updated
);
```

## CLI Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| `init-mappings` | Initialize mappings table from JSON | `python -m src.cli init-mappings` |
| `list-mappings` | Show all mappings in BigQuery | `python -m src.cli list-mappings` |
| `add-client-mapping` | Add/update a mapping | `python -m src.cli add-client-mapping "variant" "canonical"` |
| `delete-client-mapping` | Remove a mapping | `python -m src.cli delete-client-mapping "variant"` |
| `fix-client-names` | Apply mappings to meeting_intel table | `python -m src.cli fix-client-names --execute` |
| `list-clients` | Show all unique clients | `python -m src.cli list-clients --counts` |

## Code Integration

### Loading mappings in Python

```python
from src.bq_loader import BigQueryLoader

loader = BigQueryLoader()

# Load all mappings
mappings = loader.load_client_mappings()
# Returns: {'variant_name': 'canonical_name', ...}

# Add/update a mapping
loader.add_client_mapping("Variant Name", "Canonical Name", "Optional notes")

# Delete a mapping
loader.delete_client_mapping("Variant Name")

# List all mappings with metadata
mappings_list = loader.list_client_mappings()
# Returns: [{'variant_name': '...', 'canonical_name': '...', 'notes': '...', ...}, ...]
```

## Migration from JSON File

The system supports both BigQuery and file-based mappings:

**BigQuery (default, production)**:
```bash
python -m src.cli fix-client-names
```

**JSON file (legacy, local dev)**:
```bash
python -m src.cli fix-client-names --use-file
```

To migrate from JSON to BigQuery:
```bash
python -m src.cli init-mappings --from-file
```

## Current Mappings (as of Oct 25, 2025)

| Variant | → | Canonical |
|---------|---|-----------|
| `25615A3D E4C9` | → | `Unknown` (corrupted UUID fragment) |
| `Bcb88E78 88E8` | → | `Unknown` (corrupted UUID fragment) |
| `D185Be63 81B0` | → | `Unknown` (corrupted UUID fragment) |
| `Legas Delaney` | → | `Leagas Delaney` (typo fix) |
| `Omnicom / DDB` | → | `Omnicom` (normalize to parent) |
| `Sophia (creative agency...)` | → | `Sophia` (remove description) |
| `Media Arts Lab (Apple's...)` | → | `Media Arts Lab` (remove description) |
| `Your Studio (unnamed...)` | → | `Your Studio` (remove description) |
| `adam&eveDDB` | → | `adam&eveDDB` (keep as-is) |
| `Adam and Eve Recruitment` | → | `Adam and Eve Recruitment` (separate entity) |

## Advantages over JSON File

✅ **Persistent across deployments** - No need to redeploy Cloud Run to update mappings
✅ **Versionable** - `created_at` and `updated_at` timestamps track changes
✅ **Queryable** - Can join with `meeting_intel` table for analytics
✅ **Centralized** - Single source of truth for all environments
✅ **Audit trail** - Track when mappings were added/modified
✅ **No file system dependencies** - Works in any environment

## Troubleshooting

### Mappings not loading

```bash
# Check if table exists
python -m src.cli list-mappings

# If not, initialize it
python -m src.cli init-mappings
```

### Want to reset mappings

```sql
-- In BigQuery console
DELETE FROM `angular-stacker-471711-k4.unknown_brain.client_mappings` WHERE TRUE;
```

Then re-run `init-mappings`.

### Need to bulk update mappings

1. Update `client_mappings.json` file locally
2. Delete existing mappings in BigQuery (SQL above)
3. Re-import: `python -m src.cli init-mappings`

## See Also

- [CLIENT_NAME_MANAGEMENT.md](CLIENT_NAME_MANAGEMENT.md) - Complete client name management guide
- [sql/create_client_mappings_table.sql](sql/create_client_mappings_table.sql) - Table creation SQL
- [sql/create_normalized_client_view.sql](sql/create_normalized_client_view.sql) - Normalized view for querying
