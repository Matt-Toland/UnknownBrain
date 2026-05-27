"""
Cost-log writer for LLM calls.

One row per call to `scoring_cost_log` in BigQuery. Cost is estimated from
hardcoded per-model USD-per-1k-token rates and stored at write time so the
log is self-contained — no future joins to a price catalogue.

Token capture handles both OpenAI APIs:
  - Chat Completions:  response.usage.prompt_tokens / completion_tokens
  - Responses API:     response.usage.input_tokens / output_tokens

Failures are best-effort and non-fatal. A scoring run that can't log its
cost should still complete and write to meeting_intel; we'd rather lose a
cost-log row than fail a real piece of work over telemetry.

Set SCORING_COST_LOG_DISABLED=true to skip writes entirely (used in tests
and any environment without BigQuery access).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


# USD per 1K tokens (input, output). Rough but enough for telemetry.
# Sources: OpenAI pricing as of January 2026.
COST_TABLE: dict[str, Tuple[float, float]] = {
    "gpt-5":             (0.00125, 0.01000),
    "gpt-5-mini":        (0.00025, 0.00200),
    "gpt-5-nano":        (0.00005, 0.00040),
    "gpt-5-pro":         (0.01500, 0.12000),
    "gpt-5-chat-latest": (0.00025, 0.00200),
    "gpt-4o":            (0.00250, 0.01000),
    "gpt-4o-mini":       (0.00015, 0.00060),
    "o1-preview":        (0.01500, 0.06000),
    "o1-mini":           (0.00300, 0.01200),
}


def _lookup_cost(model: str) -> Optional[Tuple[float, float]]:
    """Exact match first, then prefix match for variants (e.g. gpt-4o-2024-08-06)."""
    if model in COST_TABLE:
        return COST_TABLE[model]
    # Longest-prefix match — order matters so we don't match 'gpt-5' before 'gpt-5-mini'.
    for prefix in sorted(COST_TABLE, key=len, reverse=True):
        if model.startswith(prefix):
            return COST_TABLE[prefix]
    return None


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> Optional[float]:
    rates = _lookup_cost(model)
    if rates is None:
        return None
    in_rate, out_rate = rates
    return round(tokens_in * in_rate / 1000 + tokens_out * out_rate / 1000, 6)


def extract_tokens(response: Any) -> Tuple[int, int]:
    """
    Extract (tokens_in, tokens_out) from an OpenAI response object.

    Handles both Chat Completions and Responses API shapes; returns (0, 0)
    if the response has no usage info (e.g. unit tests with bare mocks).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    # Responses API
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if input_tokens is not None and output_tokens is not None:
        return int(input_tokens or 0), int(output_tokens or 0)
    # Chat Completions
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if prompt_tokens is not None and completion_tokens is not None:
        return int(prompt_tokens or 0), int(completion_tokens or 0)
    return 0, 0


# BigQuery client is lazy-initialised on first write. Module-level cache so
# we don't pay client construction on every LLM call.
_bq_client = None  # type: ignore[var-annotated]
_bq_table_ref: Optional[str] = None


def _get_bq_target() -> Tuple[Any, str]:
    """Return (BigQuery client, fully-qualified table ref). Lazy + cached."""
    global _bq_client, _bq_table_ref
    if _bq_client is None or _bq_table_ref is None:
        from google.cloud import bigquery  # local import keeps import-graph light

        project = os.getenv("BQ_PROJECT_ID")
        dataset = os.getenv("BQ_NEW_DATASET", "unknown_brain")
        table = os.getenv("BQ_COST_LOG_TABLE", "scoring_cost_log")
        _bq_client = bigquery.Client(project=project) if project else bigquery.Client()
        _bq_table_ref = f"{_bq_client.project}.{dataset}.{table}"
    return _bq_client, _bq_table_ref


def log_llm_call(
    *,
    meeting_id: str,
    scoring_domain: str,
    model: str,
    prompt_label: Optional[str],
    response: Any,
    scored_at: Optional[datetime] = None,
) -> None:
    """
    Write a row to scoring_cost_log. Best-effort; never raises.

    The disable switch (SCORING_COST_LOG_DISABLED) short-circuits before
    any BQ I/O. Tests rely on this for hermetic unit runs; production
    leaves it unset.
    """
    if os.getenv("SCORING_COST_LOG_DISABLED", "").lower() in {"true", "1", "yes"}:
        return

    try:
        tokens_in, tokens_out = extract_tokens(response)
        cost = estimate_cost_usd(model, tokens_in, tokens_out)
        scored_at = scored_at or datetime.now(timezone.utc)
        row = {
            "log_id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "scoring_domain": scoring_domain,
            "model": model,
            "prompt_label": prompt_label,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_estimate_usd": cost,
            # BigQuery accepts ISO 8601; scored_at column is TIMESTAMP.
            "scored_at": scored_at.isoformat(),
        }
        client, table_ref = _get_bq_target()
        errors = client.insert_rows_json(table_ref, [row])
        if errors:
            logger.warning(f"scoring_cost_log streaming insert returned errors (non-fatal): {errors}")
    except Exception as e:
        logger.warning(f"scoring_cost_log write failed (non-fatal): {e}")
