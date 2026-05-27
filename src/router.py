"""
Source-aware scorer routing.

Resolves the `source` custom-metadata field on a GCS object and dispatches
to the appropriate scorer.

`resolve_source` is strict: it RAISES if the metadata is missing, has no
`source` key, or has an empty/None value. The default-to-client behaviour
was removed once every production blob was backfilled with an explicit
source (brain-uploader sets source on every new upload via the Zap,
and scripts/backfill_unlabelled_client_blobs.py covered the historicals).
Missing source on an incoming blob now signals a real bug (Zap
misconfigured, out-of-band gsutil cp, etc.) and must fail loudly rather
than silently get scored as client.
"""

from typing import Any, Mapping, Optional, Union

from .scorers import ClientScorer, TalentScorer


KNOWN_SOURCES = {"client", "talent"}


def resolve_source(metadata: Optional[Mapping[str, Any]]) -> str:
    """
    Resolve the routing source from a GCS blob's custom metadata.

    Raises ValueError if metadata is missing/empty, has no `source` key,
    or has an empty/whitespace value. Pass-through (no validation) for
    non-empty values — get_scorer validates the value is in KNOWN_SOURCES.
    """
    if not metadata:
        raise ValueError(
            "Blob has no custom metadata; 'source' is required "
            "(expected one of {client, talent})."
        )
    raw = metadata.get("source")
    if raw is None:
        raise ValueError(
            "Blob custom metadata has no 'source' key; "
            "expected one of {client, talent}."
        )
    resolved = str(raw).strip().lower()
    if not resolved:
        raise ValueError(
            "Blob custom metadata 'source' is empty/whitespace; "
            "expected one of {client, talent}."
        )
    return resolved


def get_scorer(
    source: str, *, model: Optional[str] = None
) -> Union[ClientScorer, TalentScorer]:
    """
    Return the scorer for a resolved source string, or raise.

    - "client"  -> ClientScorer(model=...)
    - "talent"  -> TalentScorer(model=...)
    - anything else -> ValueError
    """
    if source == "client":
        return ClientScorer(model=model)
    if source == "talent":
        return TalentScorer(model=model)
    raise ValueError(
        f"Unknown source: {source!r}. Expected one of {sorted(KNOWN_SOURCES)}."
    )
