"""
Bounded-retry wrapper for transient OpenAI failures.

Context: since the Granola poller went live, the Cloud Run scorer is the SOLE
writer to `meeting_intel`. During the talent backfill, a transient OpenAI
`APITimeoutError` mid Pass-1 caused the meeting to be silently dropped — no row,
no auto-retry (the claim was created, scoring threw, and the background task had
already returned 200 so Eventarc never redelivered). One transient hiccup =
a permanently missing row, invisible without an API-vs-BQ reconcile.

This retries genuinely transient errors (timeout / rate-limit / connection /
5xx / 429) in-process with bounded exponential backoff + jitter, then re-raises
on exhaustion so the caller can release its claim and signal a redeliverable
failure. Permanent errors (bad request, auth, schema validation) are NOT retried
— they re-raise immediately.
"""
from __future__ import annotations

import logging
import os
import random
import time
from typing import Callable, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Tunable via env so ops can dial retry aggression without a redeploy.
DEFAULT_MAX_ATTEMPTS = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS", "5"))
DEFAULT_BASE_DELAY = float(os.getenv("LLM_RETRY_BASE_DELAY", "1.0"))
DEFAULT_MAX_DELAY = float(os.getenv("LLM_RETRY_MAX_DELAY", "30.0"))


def _transient_types() -> Tuple[type, ...]:
    """
    OpenAI SDK exception classes we treat as transient. Resolved defensively so
    the module still imports if a given openai version lacks one of them.
    """
    try:
        import openai
    except Exception:  # pragma: no cover - openai always present in prod
        return tuple()
    names = ("APITimeoutError", "RateLimitError", "APIConnectionError", "InternalServerError")
    return tuple(t for t in (getattr(openai, n, None) for n in names) if t is not None)


def is_transient(exc: BaseException) -> bool:
    """
    True for errors worth retrying: known transient SDK types, OR any error
    carrying a 429 / 5xx HTTP status (covers APIStatusError subclasses we didn't
    name explicitly).
    """
    if isinstance(exc, _transient_types()):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    return False


def call_with_transient_retry(
    fn: Callable[[], T],
    *,
    label: str = "openai_call",
    max_attempts: Optional[int] = None,
    base_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """
    Call `fn()` and retry on transient errors with exponential backoff + jitter.

    Args:
        fn: zero-arg callable performing the OpenAI request.
        label: log label identifying the call site.
        max_attempts: total attempts (including the first). Default from env (5).
        base_delay/max_delay: backoff bounds in seconds. Defaults from env.
        sleep: injectable for tests (so they don't actually wait).

    Returns fn()'s result. Re-raises the last exception once retries are
    exhausted, or immediately for non-transient errors.
    """
    max_attempts = max_attempts or DEFAULT_MAX_ATTEMPTS
    base_delay = DEFAULT_BASE_DELAY if base_delay is None else base_delay
    max_delay = DEFAULT_MAX_DELAY if max_delay is None else max_delay

    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:
            if not is_transient(exc) or attempt >= max_attempts:
                if is_transient(exc):
                    logger.error(
                        "%s: transient %s persisted after %d attempt(s); giving up: %s",
                        label, type(exc).__name__, attempt, exc,
                    )
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)  # jitter to avoid thundering herd
            logger.warning(
                "%s: transient %s (attempt %d/%d); retrying in %.1fs",
                label, type(exc).__name__, attempt, max_attempts, delay,
            )
            sleep(delay)
