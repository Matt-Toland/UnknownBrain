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

    def test_main_write_path_includes_talent_placeholders(self):
        # Talent-specific columns must be present in the row dict (NULL/empty)
        # so MERGE has values to read.
        src = pathlib.Path("main.py").read_text()
        for col in NEW_COLUMNS - {"scoring_domain"}:
            self.assertIn(
                f"'{col}'",
                src,
                f"main.py BQ row dict missing placeholder for {col}",
            )


if __name__ == "__main__":
    unittest.main()
