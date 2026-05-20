"""
Tests for source-aware cache key construction.

Without source in the key, a client-scored result would be silently
returned for a talent re-run of the same meeting_id+model, bypassing
the router's loud-failure guard.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.gcs_client import GCSClient


class TestCacheKeyIncludesSource(unittest.TestCase):

    def setUp(self):
        # Avoid touching the real storage.Client constructor.
        with patch("src.gcs_client.storage.Client"):
            self.gcs = GCSClient(bucket_name="test-bucket")

    def test_key_contains_source(self):
        key = self.gcs.create_cache_key("abc-123", "gpt-5-mini", "client")
        self.assertTrue(key.endswith("/abc-123-gpt-5-mini-client.json"), key)

    def test_keys_differ_by_source(self):
        client_key = self.gcs.create_cache_key("m1", "gpt-5-mini", "client")
        talent_key = self.gcs.create_cache_key("m1", "gpt-5-mini", "talent")
        self.assertNotEqual(client_key, talent_key)

    def test_keys_differ_by_model(self):
        # Sanity: pre-existing model separation still holds
        a = self.gcs.create_cache_key("m1", "gpt-5-mini", "client")
        b = self.gcs.create_cache_key("m1", "gpt-4o", "client")
        self.assertNotEqual(a, b)

    def test_get_cached_score_looks_up_source_keyed_path(self):
        with patch.object(self.gcs, "file_exists", return_value=False) as mock_exists:
            self.gcs.get_cached_score("m1", "gpt-5-mini", "talent")
            args, _ = mock_exists.call_args
            self.assertIn("talent", args[0])
            self.assertNotIn("-client.json", args[0])

    def test_cache_score_writes_source_keyed_path_and_payload(self):
        with patch.object(self.gcs, "upload_results", return_value="ok") as mock_upload:
            self.gcs.cache_score("m1", "gpt-5-mini", "client", {"total_qualified_sections": 5})
            payload, path = mock_upload.call_args[0]
            self.assertIn("-client.json", path)
            self.assertEqual(payload["source"], "client")
            self.assertEqual(payload["meeting_id"], "m1")
            self.assertEqual(payload["model"], "gpt-5-mini")


if __name__ == "__main__":
    unittest.main()
