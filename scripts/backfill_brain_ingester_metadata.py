#!/usr/bin/env python
"""
One-off backfill: rewrite stale `source: brain-ingester` custom metadata
on transcripts in the unknown-brain-transcripts bucket to `source: client`.

Context: brain-ingester was a defunct alternative ingestion path that
stamped its service name into the `source` field of each blob it
uploaded. Those blobs are real client conversations; the metadata is
just stale. The source-aware router (see src/router.py) is strict —
it only accepts `client` or `talent` — so the stale value would
otherwise cause a ValueError on the next Eventarc event for each blob.

Usage:
    python scripts/backfill_brain_ingester_metadata.py            # dry-run
    python scripts/backfill_brain_ingester_metadata.py --apply    # mutate

Requires GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account
key with storage.objects.update on the bucket.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google.cloud import storage


BUCKET = "unknown-brain-transcripts"
PREFIX = "transcripts/"
STALE_VALUE = "brain-ingester"
TARGET_VALUE = "client"


def find_stale_blobs(client: storage.Client) -> list[storage.Blob]:
    """Return blobs whose custom metadata 'source' equals STALE_VALUE."""
    stale = []
    for blob in client.list_blobs(BUCKET, prefix=PREFIX):
        blob.reload()  # ensure custom metadata is populated
        if (blob.metadata or {}).get("source") == STALE_VALUE:
            stale.append(blob)
    return stale


def rewrite(blob: storage.Blob) -> dict:
    """Replace 'source' with TARGET_VALUE, preserving every other key."""
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
    stale = find_stale_blobs(client)

    print(f"Bucket: gs://{BUCKET}/{PREFIX}")
    print(f"Found {len(stale)} blob(s) with source={STALE_VALUE!r}:\n")
    for b in stale:
        print(f"  - {b.name}")
        print(f"      before: {b.metadata!r}")

    if not stale:
        print("\nNothing to do.")
        return 0

    if not args.apply:
        print(f"\nDry-run. Re-run with --apply to rewrite source -> {TARGET_VALUE!r}.")
        return 0

    print(f"\nRewriting source -> {TARGET_VALUE!r} (preserving all other metadata)...")
    for b in stale:
        after = rewrite(b)
        print(f"  ✓ {b.name}")
        print(f"      after:  {after!r}")

    print(f"\nDone. {len(stale)} blob(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
