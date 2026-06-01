"""
Tests for the BigQuery schema additions that prepare meeting_intel for
talent-domain writes.

This PR adds 10 columns but no talent scoring code. Client writes
explicitly stamp scoring_domain='client' and leave the talent-specific
columns NULL/empty; the MERGE statement must list every new column in
its UPDATE SET clause so an upsert from a talent scorer (in a future
PR) doesn't silently drop fields.
"""

import pathlib
import unittest
from unittest.mock import patch

from src.bq_loader import BigQueryLoader


NEW_COLUMNS = {
    "scoring_domain",
    "talent_now",
    "talent_triggers",
    "talent_motivation",
    "talent_market",
    "talent_leads",
    "talent_narrative",
    "mentioned_companies",
    "perception_themes",
    "articulated_blockers",
}


class TestSchemaIncludesNewColumns(unittest.TestCase):
    """The CREATE-table schema list in bq_loader must declare every new column."""

    def test_schema_includes_all_new_columns(self):
        # Spy on bigquery.Table to capture the schema list passed to construction.
        from google.cloud.exceptions import NotFound

        with patch("src.bq_loader.bigquery.Client"), \
             patch("src.bq_loader.bigquery.Table") as mock_table, \
             patch.object(BigQueryLoader, "create_dataset_if_not_exists", return_value=None):
            loader = BigQueryLoader()
            loader.client.get_table.side_effect = NotFound("force-create")
            loader.client.create_table.return_value = None

            loader.create_new_table_if_not_exists()

            self.assertTrue(mock_table.called, "bigquery.Table should have been constructed")
            # bigquery.Table(table_id, schema=...) — schema may be positional or kwarg
            schema = mock_table.call_args.kwargs.get("schema")
            if schema is None:
                schema = mock_table.call_args.args[1]
            field_names = {field.name for field in schema}

        missing = NEW_COLUMNS - field_names
        self.assertFalse(missing, f"schema missing columns: {sorted(missing)}")


class TestMergeStatementIncludesNewColumns(unittest.TestCase):
    """
    The MERGE UPDATE SET clause must reference every new column so a
    matched upsert doesn't silently drop fields on re-score.
    """

    def test_merge_update_clause_contains_every_new_column(self):
        src = pathlib.Path("src/bq_loader.py").read_text()
        for col in NEW_COLUMNS:
            self.assertIn(
                f"{col} = source.{col}",
                src,
                f"MERGE UPDATE clause does not assign {col}",
            )


class TestClientWritePathSetsScoringDomain(unittest.TestCase):
    """
    Every row written via main.upload_new_format_to_bigquery is a
    client-scored transcript and must stamp scoring_domain='client'.
    """

    def test_main_write_path_sets_scoring_domain_client(self):
        src = pathlib.Path("main.py").read_text()
        self.assertIn(
            "'scoring_domain': 'client'",
            src,
            "main.py upload_new_format_to_bigquery must explicitly set scoring_domain='client'",
        )

    def test_client_write_path_omits_talent_placeholders(self):
        # The client write path must NOT emit explicit talent-column keys.
        # Writing Python None serialised to the JSON literal `null` (not SQL
        # NULL), so `talent_now IS NULL` returned False and misled downstream
        # IS NULL filters / monitoring. Omitting the keys lets the temp-table
        # load fill them with proper SQL NULL / empty array on INSERT ROW.
        # The client MERGE doesn't reference talent columns in its SET clause,
        # so omitting them is safe.
        import re
        src = pathlib.Path("main.py").read_text()
        # Scope to the client write path (upload_new_format_to_bigquery), not
        # the whole file — the talent write path legitimately uses these keys.
        client_fn = src.split("async def upload_new_format_to_bigquery")[1].split("async def ")[0]
        talent_cols = NEW_COLUMNS - {"scoring_domain"}
        for col in talent_cols:
            self.assertNotIn(
                f"'{col}'",
                client_fn,
                f"client write path should omit talent column {col!r} (it lands as SQL NULL via INSERT ROW)",
            )


if __name__ == "__main__":
    unittest.main()
