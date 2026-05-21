#!/usr/bin/env python
"""
Relax client-domain REQUIRED columns in meeting_intel to NULLABLE.

When Brief 3 added the talent columns, the original client-domain columns
stayed `mode=REQUIRED`. That blocks Brief 4 from writing talent rows: an
INSERT ROW from a talent-only payload would fail because client_info /
total_qualified_sections / qualified / now / next / measure / blocker / fit
have no values.

The brief's "omit-from-SET, prefer SQL NULL" guidance is only feasible if
these columns are NULLABLE. Existing client rows are unaffected — they
all already have values for these fields. Going forward:

  - Client rows: still write all client fields (no behaviour change).
  - Talent rows: write talent fields only; client fields stay SQL NULL.

Columns relaxed (REQUIRED -> NULLABLE):
  - client_info (JSON)
  - total_qualified_sections (INTEGER)
  - qualified (BOOLEAN)
  - now, next, measure, blocker, fit (JSON, all five)

This is a one-way operation in BigQuery — REQUIRED columns can be relaxed
to NULLABLE, but the reverse needs a table rewrite. Confirmed safe: the
brief explicitly endorses this direction.

Usage:
    python scripts/migrate_relax_client_required_columns.py           # dry-run
    python scripts/migrate_relax_client_required_columns.py --apply   # execute
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env").resolve())

from google.cloud import bigquery  # noqa: E402

PROJECT = os.getenv("BQ_PROJECT_ID")
DATASET = os.getenv("BQ_NEW_DATASET", "unknown_brain")
TABLE = os.getenv("BQ_NEW_TABLE", "meeting_intel")

# Columns to relax REQUIRED -> NULLABLE.
COLUMNS_TO_RELAX = {
    "client_info",
    "total_qualified_sections",
    "qualified",
    "now",
    "next",
    "measure",
    "blocker",
    "fit",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually update the table schema. Without this flag, dry-run.",
    )
    args = parser.parse_args()

    if not PROJECT:
        print("ERROR: BQ_PROJECT_ID is not set in environment or .env", file=sys.stderr)
        return 2

    fq_table = f"{PROJECT}.{DATASET}.{TABLE}"
    print(f"Target: {fq_table}\n")

    client = bigquery.Client(project=PROJECT)
    table = client.get_table(fq_table)

    # Find which of the target columns are currently REQUIRED
    current_fields = {f.name: f for f in table.schema}
    to_change = []
    already_nullable = []
    missing = []
    for col in COLUMNS_TO_RELAX:
        field = current_fields.get(col)
        if field is None:
            missing.append(col)
            continue
        if field.mode == "REQUIRED":
            to_change.append(col)
        else:
            already_nullable.append(col)

    print("=== Plan ===")
    print(f"  REQUIRED -> NULLABLE ({len(to_change)}): {sorted(to_change)}")
    print(f"  already NULLABLE ({len(already_nullable)}): {sorted(already_nullable)}")
    if missing:
        print(f"  MISSING from schema ({len(missing)}): {sorted(missing)}")

    if not to_change:
        print("\nNothing to do — all target columns are already NULLABLE.")
        return 0

    if not args.apply:
        print("\nDry-run. Re-run with --apply to execute.")
        return 0

    print("\n=== Executing ===")
    new_schema = []
    for field in table.schema:
        if field.name in to_change:
            new_schema.append(
                bigquery.SchemaField(
                    name=field.name,
                    field_type=field.field_type,
                    mode="NULLABLE",
                    description=field.description,
                    fields=field.fields,
                )
            )
            print(f"  ✓ {field.name}: REQUIRED -> NULLABLE")
        else:
            new_schema.append(field)

    table.schema = new_schema
    client.update_table(table, ["schema"])

    print("\n=== Verification ===")
    updated = client.get_table(fq_table)
    updated_fields = {f.name: f for f in updated.schema}
    for col in sorted(COLUMNS_TO_RELAX):
        f = updated_fields.get(col)
        print(f"  {col:30s} mode={f.mode if f else 'MISSING'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
