"""
Source-aware scorer routing.

Resolves the `source` custom-metadata field on a GCS object and dispatches
to the appropriate scorer. Only `client` is wired up today; `talent` is a
deliberate NotImplementedError so any accidental routing fails loudly.
"""

from typing import Any, Mapping, Optional

from .scorers import ClientScorer


DEFAULT_SOURCE = "client"
KNOWN_SOURCES = {"client", "talent"}


def resolve_source(metadata: Optional[Mapping[str, Any]]) -> str:
    """
    Resolve the routing source from a GCS blob's custom metadata.

    Defaults to "client" when metadata is None, missing the key, or has an
    empty/whitespace value, so transcripts uploaded before brain-uploader
    started setting the field continue to route correctly.
    """
    if not metadata:
        return DEFAULT_SOURCE
    raw = metadata.get("source")
    if raw is None:
        return DEFAULT_SOURCE
    resolved = str(raw).strip().lower()
    return resolved or DEFAULT_SOURCE


def get_scorer(source: str, *, model: Optional[str] = None) -> ClientScorer:
    """
    Return the scorer for a resolved source string, or raise.

    - "client"  -> ClientScorer(model=...)
    - "talent"  -> NotImplementedError (intentional guard until the talent
      scorer lands in a follow-up PR)
    - anything else -> ValueError
    """
    if source == "client":
        return ClientScorer(model=model)
    if source == "talent":
        raise NotImplementedError(
            "Talent scorer not yet implemented (source='talent'). "
            "Routing skeleton is in place; the scorer lands in a follow-up PR."
        )
    raise ValueError(
        f"Unknown source: {source!r}. Expected one of {sorted(KNOWN_SOURCES)}."
    )
