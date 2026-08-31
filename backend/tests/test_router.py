"""Model routing, fallback, and the circuit breaker.

Two defects pinned here:

  * Every exception was treated as a transient tier failure. An invalid API key
    fails identically on all three tiers, so a 401 walked the whole chain,
    burned three round trips and three breaker failures, and after three
    requests every breaker was open — at which point the surfaced error became
    "Circuit breaker open" instead of "your key is wrong".
  * `LLM_DEFAULT_TIER` existed in config.py *and* .env.example and was read by
    nothing; `route` hardcoded its fallback instead.
"""

import pytest

from app.services.llm import CircuitBreaker, is_retryable
from app.services.router import ModelRouter


class FakeLLM:
    """Raises a scripted error per tier, or streams if none is scripted."""

    def __init__(self, failures: dict[str, Exception] | None = None):
        self.failures = failures or {}
        self.attempts: list[str] = []

    async def generate_stream(self, prompt, tier, context_chunks):
        self.attempts.append(tier)
        if tier in self.failures:
            raise self.failures[tier]
        yield {"type": "chunk", "text": "ok"}
        yield {"type": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "model": tier}


class FakeAuthError(Exception):
    """Shaped like the SDK's AuthenticationError: carries an HTTP status."""

    status_code = 401


class FakeOverloaded(Exception):
    status_code = 529


async def drain(router, tier, trace=None):
    return [e async for e in router.generate_with_fallback("q", tier, [], trace)]


class TestRetryableClassification:
    def test_auth_failure_is_not_retryable(self):
        assert is_retryable(FakeAuthError()) is False

    def test_bad_request_is_not_retryable(self):
        class BadRequest(Exception):
            status_code = 400

        assert is_retryable(BadRequest()) is False

    def test_overload_is_retryable(self):
        assert is_retryable(FakeOverloaded()) is True

    def test_rate_limit_is_retryable(self):
        class TooMany(Exception):
            status_code = 429

        assert is_retryable(TooMany()) is True

    def test_an_error_with_no_status_is_retryable(self):
        """A socket timeout has no status and is exactly what fallback is for."""
        assert is_retryable(TimeoutError("read timeout")) is True


class TestFallbackChain:
    async def test_a_permanent_error_does_not_walk_the_chain(self, config):
        llm = FakeLLM({t: FakeAuthError() for t in ("fast", "quality", "deep")})
        router = ModelRouter(llm, config)
        with pytest.raises(Exception):
            await drain(router, "fast")
        assert llm.attempts == ["fast"], (
            "a bad API key fails the same way on every tier; trying all three "
            f"only wastes round trips (attempted {llm.attempts})"
        )

    async def test_a_transient_error_still_walks_the_chain(self, config):
        llm = FakeLLM({"fast": FakeOverloaded()})
        router = ModelRouter(llm, config)
        events = await drain(router, "fast")
        assert llm.attempts == ["fast", "quality"]
        assert any(e["type"] == "chunk" for e in events)

    async def test_a_permanent_error_surfaces_its_own_message(self, config):
        llm = FakeLLM({t: FakeAuthError("API key is invalid") for t in ("fast", "quality", "deep")})
        router = ModelRouter(llm, config)
        with pytest.raises(Exception, match="API key is invalid"):
            await drain(router, "fast")


class TestCircuitBreakerAccounting:
    def test_a_permanent_failure_does_not_trip_the_breaker(self):
        """The upstream isn't struggling; the request was wrong."""
        breaker = CircuitBreaker()
        for _ in range(5):
            breaker.record_failure(FakeAuthError())
        assert breaker.is_open() is False

    def test_transient_failures_still_trip_it(self):
        breaker = CircuitBreaker(threshold=3)
        for _ in range(3):
            breaker.record_failure(FakeOverloaded())
        assert breaker.is_open() is True


class TestDefaultTier:
    def test_the_configured_default_is_used(self, config):
        router = ModelRouter(FakeLLM(), config.model_copy(update={"LLM_DEFAULT_TIER": "deep"}))
        assert router.route("short question") == "deep"

    def test_an_explicit_hint_still_wins(self, config):
        router = ModelRouter(FakeLLM(), config.model_copy(update={"LLM_DEFAULT_TIER": "deep"}))
        assert router.route("short question", "fast") == "fast"

    def test_a_long_query_is_promoted_above_the_default(self, config):
        router = ModelRouter(FakeLLM(), config.model_copy(update={"LLM_DEFAULT_TIER": "fast"}))
        assert router.route(" ".join(["word"] * 200)) == "quality"

    def test_an_unknown_hint_falls_back_to_the_default(self, config):
        router = ModelRouter(FakeLLM(), config.model_copy(update={"LLM_DEFAULT_TIER": "quality"}))
        assert router.route("short", "turbo") == "quality"
