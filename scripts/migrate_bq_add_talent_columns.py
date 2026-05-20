#!/usr/bin/env python
"""
Add talent-domain columns to meeting_intel and backfill
scoring_domain='client' on existing rows.

NOTE: meeting_intel has three semantically distinct fields that touch
on "source/domain" concepts. Do not conflate them.

  1. source (top-level STRING REQUIRED)
     = ingestion path. Values: granola_drive, bigquery.
       HOW a transcript entered the system.

  2. scoring_domain (top-level STRING NULLABLE) — added in this migration
     = which scorer runs on it. Values: client, talent.
       WHAT KIND of conversation it is.

  3. client_info.domain (nested JSON field)
     = client's business sector. Values: fintech, healthcare, etc.
       The CLIENT'S industry.

This script:
  1. Adds 10 NEW columns to meeting_intel (idempotent via ADD COLUMN
     IF NOT EXISTS): the routing `scoring_domain` column, six
     talent-specific scoring buckets, and three per-client intelligence
     extensions.
  2. Backfills scoring_domain='client' on every existing row
     (273 last checked).
  3. Verifies by printing the post-migration scoring_domain
     distribution and the new row count.

The talent-specific columns sit NULL on every existing and every new
client row until the TalentScorer is added in a later PR. The MERGE
statement in bq_loader.py is updated in this same PR so MERGE doesn't
blow up when the talent scorer eventually populates them.

Usage:
    python scripts/migrate_bq_add_talent_columns.py           # dry-run
    python scripts/migrate_bq_add_talent_columns.py --apply   # execute

Requires GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account
key with bigquery.tables.update on the dataset.
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

# (column_name, BigQuery type for ALTER TABLE).
# ARRAY<T> in DDL == REPEATED mode T in SchemaField.
NEW_COLUMNS: list[tuple[str, str]] = [
    # Routing
    ("scoring_domain", "STRING"),
    # Talent-specific scoring buckets (finalised with Carrie)
    ("talent_now", "JSON"),
    ("talent_triggers", "ARRAY<STRING>"),
    ("talent_motivation", "JSON"),
    ("talent_market", "JSON"),
    ("talent_leads", "JSON"),
    ("talent_narrative", "STRING"),
    # Per-client intelligence report extensions (added late by Ollie)
    ("mentioned_companies", "ARRAY<JSON>"),
    ("perception_themes", "ARRAY<JSON>"),
    ("articulated_blockers", "ARRAY<JSON>"),
]


def build_statements(fq_table: str) -> tuple[list[str], str]:
    ddl = [
        f"ALTER TABLE {fq_table} ADD COLUMN IF NOT EXISTS {name} {typ}"
        for name, typ in NEW_COLUMNS
    ]
    backfill = (
        f"UPDATE {fq_table} SET scoring_domain = 'client' "
        f"WHERE scoring_domain IS NULL"
    )
    return ddl, backfill


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually execute the DDL + backfill. Without this flag, dry-run.",
    )
    args = parser.parse_args()

    if not PROJECT:
        print("ERROR: BQ_PROJECT_ID is not set in environment or .env", file=sys.stderr)
        return 2

    fq_table = f"`{PROJECT}.{DATASET}.{TABLE}`"
    ddl, backfill = build_statements(fq_table)

    print(f"Target: {fq_table}")
    print(f"Columns to add: {len(NEW_COLUMNS)}\n")

    print("=== DDL ===")
    for stmt in ddl:
        print(f"  {stmt};")

    print("\n=== Backfill ===")
    print(f"  {backfill};")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to execute.")
        return 0

    print("\n=== Executing ===")
    client = bigquery.Client(project=PROJECT)
    for stmt in ddl:
        client.query(stmt).result()
        print(f"  ✓ {stmt}")
    client.query(backfill).result()
    print(f"  ✓ {backfill}")

    print("\n=== Verification ===")
    dist_q = (
        f"SELECT scoring_domain, COUNT(*) AS n FROM {fq_table} "
        f"GROUP BY scoring_domain ORDER BY n DESC"
    )
    for row in client.query(dist_q).result():
        print(f"  scoring_domain={row['scoring_domain']!r:15s} count={row['n']}")

    total_row = next(iter(client.query(f"SELECT COUNT(*) AS t FROM {fq_table}").result()))
    print(f"\nTotal rows: {total_row['t']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
