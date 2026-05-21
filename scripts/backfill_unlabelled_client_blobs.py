#!/usr/bin/env python
"""
Backfill source='client' onto every transcript blob that currently has
no source metadata.

Context: prior to the brain-uploader Zap setting `source: <client|talent>`,
transcripts were uploaded without that custom metadata. ~269 such blobs
remain. The router is being tightened so that resolve_source(None) RAISES
instead of silently defaulting — but every existing untagged blob would
then fail processing on the next re-trigger. This script tags them all
once so the strict router is safe to deploy.

NOTE: every blob touched by this script is assumed to be a client
transcript. As of 2026-05-21, talent transcripts are still NOT in
production (TalentScorer / talent ingestion path lands in Brief 4).
Every historical blob in transcripts/ predates talent.

Usage:
    python scripts/backfill_unlabelled_client_blobs.py            # dry-run
    python scripts/backfill_unlabelled_client_blobs.py --apply    # mutate

Preserves all other custom metadata keys (documentId, title, createdAt,
etc.) when stamping source='client'.

Requires GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account
key with storage.objects.update on the bucket.
"""
from __future__ import annotations

import argparse
import sys

from google.cloud import storage


BUCKET = "unknown-brain-transcripts"
PREFIX = "transcripts/"
TARGET_VALUE = "client"


def find_untagged_blobs(client: storage.Client) -> list[storage.Blob]:
    """Return blobs whose custom metadata has no 'source' or empty source."""
    untagged = []
    for blob in client.list_blobs(BUCKET, prefix=PREFIX):
        blob.reload()
        md = blob.metadata or {}
        raw = md.get("source")
        resolved = str(raw).strip().lower() if raw is not None else ""
        if not resolved:
            untagged.append(blob)
    return untagged


def stamp(blob: storage.Blob) -> dict:
    """Add source=TARGET_VALUE while preserving every other key."""
    existing = dict(blob.metadata or {})
    existing["source"] = TARGET_VALUE
    blob.metadata = existing
    blob.patch()
    blob.reload()
    return blob.metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite metadata. Without this flag, runs as dry-run.",
    )
    args = parser.parse_args()

    client = storage.Client()
    untagged = find_untagged_blobs(client)

    print(f"Bucket: gs://{BUCKET}/{PREFIX}")
    print(f"Found {len(untagged)} blob(s) with no/empty source metadata.\n")

    if not untagged:
        print("Nothing to do.")
        return 0

    # Show only the first 10 + last 5 to keep dry-run output manageable.
    preview = untagged[:10] + ([None] + untagged[-5:] if len(untagged) > 15 else [])
    for entry in preview:
        if entry is None:
            print(f"  ... ({len(untagged) - 15} more) ...")
            continue
        existing_keys = sorted((entry.metadata or {}).keys())
        print(f"  - {entry.name}")
        print(f"      existing metadata keys: {existing_keys or '<none>'}")

    if not args.apply:
        print(f"\nDry-run. Re-run with --apply to stamp source={TARGET_VALUE!r}.")
        return 0

    print(f"\nStamping source={TARGET_VALUE!r} on {len(untagged)} blob(s)...")
    for i, blob in enumerate(untagged, 1):
        stamp(blob)
        if i % 25 == 0 or i == len(untagged):
            print(f"  [{i}/{len(untagged)}] {blob.name}")

    print(f"\nDone. {len(untagged)} blob(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
