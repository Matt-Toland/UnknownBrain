#!/usr/bin/env python
"""
Create the scoring_cost_log BigQuery table.

One row per LLM call so cost can be reconstructed at query time by
domain, model, prompt, or meeting. No aggregation in code — joins and
roll-ups happen in SQL.

A single talent meeting writes ~2 rows (structured extraction + narrative).
A single client meeting writes ~14 rows (5 opportunity checks + taxonomy
+ client extraction + 8 sales-assessment checks when enabled). Real volumes
are tiny in absolute terms; a STRING log_id keyed per row is plenty.

Schema:
    log_id            STRING       NOT NULL  (uuid generated at write time)
    meeting_id        STRING       NOT NULL
    scoring_domain    STRING       NOT NULL  ('client' or 'talent')
    model             STRING       NOT NULL
    prompt_label      STRING       NULLABLE  (e.g. 'opportunity_now', 'talent_extraction')
    tokens_in         INTEGER      NOT NULL
    tokens_out        INTEGER      NOT NULL
    cost_estimate_usd FLOAT64      NULLABLE  (computed from token counts at write time)
    scored_at         TIMESTAMP    NOT NULL

Usage:
    python scripts/migrate_create_scoring_cost_log.py           # dry-run
    python scripts/migrate_create_scoring_cost_log.py --apply   # execute

Requires GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account
key with bigquery.tables.create on the dataset.
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
TABLE = os.getenv("BQ_COST_LOG_TABLE", "scoring_cost_log")


def build_ddl(fq_table: str) -> str:
    # CREATE TABLE IF NOT EXISTS so re-running is safe.
    return f"""\
CREATE TABLE IF NOT EXISTS {fq_table} (
    log_id            STRING    NOT NULL OPTIONS(description="UUID for this LLM call"),
    meeting_id        STRING    NOT NULL OPTIONS(description="Meeting being scored"),
    scoring_domain    STRING    NOT NULL OPTIONS(description="'client' or 'talent'"),
    model             STRING    NOT NULL OPTIONS(description="LLM model name"),
    prompt_label      STRING             OPTIONS(description="Which prompt this call corresponds to (e.g. opportunity_now, talent_extraction, talent_narrative)"),
    tokens_in         INT64     NOT NULL OPTIONS(description="Input/prompt tokens"),
    tokens_out        INT64     NOT NULL OPTIONS(description="Output/completion tokens"),
    cost_estimate_usd FLOAT64            OPTIONS(description="Estimated cost in USD, computed at write time"),
    scored_at         TIMESTAMP NOT NULL OPTIONS(description="When this LLM call ran")
)
OPTIONS(description="One row per LLM call. Reconstruct cost by domain/model/prompt/meeting via SQL.")
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually execute the CREATE TABLE. Without this flag, dry-run.",
    )
    args = parser.parse_args()

    if not PROJECT:
        print("ERROR: BQ_PROJECT_ID is not set in environment or .env", file=sys.stderr)
        return 2

    fq_table = f"`{PROJECT}.{DATASET}.{TABLE}`"
    ddl = build_ddl(fq_table)

    print(f"Target: {fq_table}\n")
    print("=== DDL ===")
    print(ddl)

    if not args.apply:
        print("Dry-run. Re-run with --apply to execute.")
        return 0

    print("=== Executing ===")
    client = bigquery.Client(project=PROJECT)
    client.query(ddl).result()
    print(f"  ✓ created {fq_table}")

    print("\n=== Verification ===")
    table_ref = f"{PROJECT}.{DATASET}.{TABLE}"
    table = client.get_table(table_ref)
    print(f"  Table:          {table.full_table_id}")
    print(f"  Created:        {table.created.isoformat() if table.created else 'unknown'}")
    print(f"  Schema fields:  {len(table.schema)}")
    print(f"  Rows:           {table.num_rows}")
    print()
    for field in table.schema:
        print(f"    {field.name:20s} {field.field_type:10s} {field.mode}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
