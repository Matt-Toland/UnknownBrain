"""
Tests for src/llm_retry.call_with_transient_retry.

Covers the resilience contract added after the poller went live: transient
OpenAI errors (timeout / rate-limit / connection / 5xx) are retried with bounded
backoff; permanent errors are not; exhaustion re-raises. `sleep` is injected so
tests never actually wait.
"""
import unittest

import openai

from src.llm_retry import call_with_transient_retry, is_transient


def _make_openai_error(cls):
    """Construct an OpenAI SDK error without a live API call.

    The SDK error constructors vary by type/version, so fall back to
    __new__ (bypassing __init__) when a simple construction isn't possible —
    we only care about the type for is_transient()."""
    try:
        if cls is openai.APITimeoutError:
            return cls(request=None)
        return cls.__new__(cls)
    except Exception:
        return cls.__new__(cls)


class _Status5xx(Exception):
    """Stand-in for an APIStatusError-like object carrying a 5xx status."""
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class TestIsTransient(unittest.TestCase):
    def test_timeout_is_transient(self):
        self.assertTrue(is_transient(_make_openai_error(openai.APITimeoutError)))

    def test_rate_limit_is_transient(self):
        self.assertTrue(is_transient(_make_openai_error(openai.RateLimitError)))

    def test_connection_error_is_transient(self):
        self.assertTrue(is_transient(_make_openai_error(openai.APIConnectionError)))

    def test_5xx_status_is_transient(self):
        self.assertTrue(is_transient(_Status5xx(503)))
        self.assertTrue(is_transient(_Status5xx(500)))

    def test_429_status_is_transient(self):
        self.assertTrue(is_transient(_Status5xx(429)))

    def test_plain_value_error_is_not_transient(self):
        self.assertFalse(is_transient(ValueError("bad input")))

    def test_4xx_status_not_transient(self):
        self.assertFalse(is_transient(_Status5xx(400)))


class TestCallWithTransientRetry(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def _sleep(self, d):
        self.sleeps.append(d)

    def test_succeeds_first_try_no_sleep(self):
        out = call_with_transient_retry(lambda: 42, sleep=self._sleep)
        self.assertEqual(out, 42)
        self.assertEqual(self.sleeps, [])

    def test_retries_transient_then_succeeds(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _Status5xx(503)
            return "ok"

        out = call_with_transient_retry(fn, max_attempts=5, base_delay=1.0, sleep=self._sleep)
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 3)
        # slept twice (after attempts 1 and 2), exponential: ~1s then ~2s (+jitter)
        self.assertEqual(len(self.sleeps), 2)
        self.assertGreaterEqual(self.sleeps[0], 1.0)
        self.assertGreaterEqual(self.sleeps[1], 2.0)

    def test_exhausts_and_reraises_transient(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise _Status5xx(500)

        with self.assertRaises(_Status5xx):
            call_with_transient_retry(fn, max_attempts=4, base_delay=0.5, sleep=self._sleep)
        self.assertEqual(calls["n"], 4)          # tried exactly max_attempts
        self.assertEqual(len(self.sleeps), 3)    # slept between attempts only

    def test_permanent_error_not_retried(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("malformed request")

        with self.assertRaises(ValueError):
            call_with_transient_retry(fn, max_attempts=5, sleep=self._sleep)
        self.assertEqual(calls["n"], 1)          # no retry
        self.assertEqual(self.sleeps, [])

    def test_backoff_capped_at_max_delay(self):
        def fn():
            raise _Status5xx(503)

        with self.assertRaises(_Status5xx):
            call_with_transient_retry(
                fn, max_attempts=10, base_delay=1.0, max_delay=4.0, sleep=self._sleep
            )
        # every recorded sleep must respect the cap (+25% jitter ceiling)
        self.assertTrue(all(d <= 4.0 * 1.25 + 1e-9 for d in self.sleeps), self.sleeps)


if __name__ == "__main__":
    unittest.main()
