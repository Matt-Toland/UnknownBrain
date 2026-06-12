#!/usr/bin/env python
"""
Add the Article 9 row-outcome column to meeting_intel.

Adds ONE column (idempotent via ADD COLUMN IF NOT EXISTS):

  article9_status  STRING
      Row-level Article 9 outcome, written by the TALENT scorer only:
      'flag' | 'redacted' | 'redact_fallback'. `redact_fallback` marks a meeting
      that could not be auto-redacted and was stored with data retained for
      manual review — query these to monitor the fail-closed/fallback rate.
      NULL on existing rows and on client rows.

No backfill (NULL is correct for rows scored before this column existed). The
talent MERGE in bq_loader.py writes it; the client MERGE does not reference it.

Usage:
    python scripts/migrate_bq_add_article9_status.py           # dry-run (default)
    python scripts/migrate_bq_add_article9_status.py --apply    # execute

Requires GOOGLE_APPLICATION_CREDENTIALS with bigquery.tables.update on the dataset.
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

NEW_COLUMNS: list[tuple[str, str]] = [
    ("article9_status", "STRING"),
]


def build_statements(fq_table: str) -> list[str]:
    return [
        f"ALTER TABLE {fq_table} ADD COLUMN IF NOT EXISTS {name} {typ}"
        for name, typ in NEW_COLUMNS
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually execute the DDL. Without this flag, dry-run.",
    )
    args = parser.parse_args()

    if not PROJECT:
        print("ERROR: BQ_PROJECT_ID is not set in environment or .env", file=sys.stderr)
        return 2

    fq_table = f"`{PROJECT}.{DATASET}.{TABLE}`"
    ddl = build_statements(fq_table)

    print(f"Target: {fq_table}")
    print(f"Columns to add: {len(NEW_COLUMNS)}\n")

    print("=== DDL ===")
    for stmt in ddl:
        print(f"  {stmt};")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to execute.")
        return 0

    print("\n=== Executing ===")
    client = bigquery.Client(project=PROJECT)
    for stmt in ddl:
        client.query(stmt).result()
        print(f"  ✓ {stmt}")

    print("\n=== Verification ===")
    table = client.get_table(f"{PROJECT}.{DATASET}.{TABLE}")
    col = next((f for f in table.schema if f.name == "article9_status"), None)
    if col is None:
        print("  ✗ article9_status NOT found post-migration", file=sys.stderr)
        return 1
    print(f"  ✓ article9_status present — type={col.field_type} mode={col.mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
