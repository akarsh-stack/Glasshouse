"""Token bucket behaviour.

Three defects are pinned here:

  * The Redis path reported `retry_after = tokens_requested / refill_rate`, a
    constant, because the Lua script never told Python how much budget was
    actually left. Every rejection claimed 0.1s regardless of the real deficit.
  * In-memory buckets were a plain dict that nothing ever evicted, so a client
    rotating session ids grew the process's memory without bound. The Redis
    path had `EXPIRE 3600`; the fallback had nothing.
  * The bucket was keyed on a client-supplied `session_id`, so rotating it
    granted a fresh budget. The frontend mints a new one per page load.
"""

import pytest
from conftest import FakeEmbeddingService  # noqa: F401  (keeps conftest on the path)

from app.services.rate_limiter import TokenBucketRateLimiter, retry_after_for


class TestRetryAfterArithmetic:
    """`retry_after` is the wait until the deficit refills, not a constant."""

    def test_empty_bucket_waits_for_one_token(self):
        assert retry_after_for(remaining=0.0, requested=1, refill_rate=10.0) == 0.1

    def test_partial_budget_shortens_the_wait(self):
        assert retry_after_for(remaining=0.5, requested=1, refill_rate=10.0) == 0.05

    def test_a_larger_request_waits_longer(self):
        assert retry_after_for(remaining=0.0, requested=5, refill_rate=10.0) == 0.5

    def test_a_slower_refill_waits_longer(self):
        assert retry_after_for(remaining=0.0, requested=1, refill_rate=2.0) == 0.5

    def test_sufficient_budget_never_reports_a_negative_wait(self):
        assert retry_after_for(remaining=9.0, requested=1, refill_rate=10.0) == 0.0


class FakeRedis:
    """Stands in for the socket, not for the script.

    `eval` returns whatever the test says the server returned, so this exercises
    Python's handling of the script's contract — `[allowed, milli_tokens]` —
    without pretending to interpret Lua.
    """

    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    async def eval(self, script, numkeys, *args):
        self.calls.append((numkeys, args))
        return self.result


class TestRedisPathReportsARealDeficit:
    async def test_rejection_uses_the_remaining_budget_from_the_script(self, config):
        # Script says: not allowed, 300 milli-tokens (0.3) left in the tightest bucket.
        limiter = TokenBucketRateLimiter(config, redis_client=FakeRedis([0, 300]))
        result = await limiter.check_and_consume("s1", client_ip="10.0.0.1")
        assert result["allowed"] is False
        # 1 token wanted, 0.3 available, refilling at 10/s -> 0.07s
        assert result["retry_after"] == pytest.approx(0.07)

    async def test_an_empty_bucket_reports_the_full_wait(self, config):
        limiter = TokenBucketRateLimiter(config, redis_client=FakeRedis([0, 0]))
        result = await limiter.check_and_consume("s1", client_ip="10.0.0.1")
        assert result["retry_after"] == pytest.approx(0.1)

    async def test_admission_reports_no_retry(self, config):
        limiter = TokenBucketRateLimiter(config, redis_client=FakeRedis([1, 99000]))
        result = await limiter.check_and_consume("s1", client_ip="10.0.0.1")
        assert result == {"allowed": True, "retry_after": None}

    async def test_both_the_session_and_the_ip_bucket_are_sent(self, config):
        redis = FakeRedis([1, 99000])
        limiter = TokenBucketRateLimiter(config, redis_client=redis)
        await limiter.check_and_consume("s1", client_ip="10.0.0.1")
        numkeys, args = redis.calls[0]
        assert numkeys == 2
        assert "gh:ratelimit:session:s1" in args
        assert "gh:ratelimit:ip:10.0.0.1" in args


class TestInMemoryFallback:
    async def test_rejection_reports_a_real_deficit(self, config):
        limiter = TokenBucketRateLimiter(config, redis_client=None)
        for _ in range(config.RATE_LIMIT_TOKENS):
            assert (await limiter.check_and_consume("s1"))["allowed"] is True
        rejected = await limiter.check_and_consume("s1")
        assert rejected["allowed"] is False
        assert 0 < rejected["retry_after"] <= 0.1

    async def test_rotating_the_session_id_does_not_grant_fresh_budget(self, config):
        """The per-IP bucket is the backstop the session bucket can't be."""
        limiter = TokenBucketRateLimiter(config, redis_client=None)
        admitted = 0
        for i in range(2000):
            result = await limiter.check_and_consume(f"session-{i}", client_ip="10.0.0.9")
            if result["allowed"]:
                admitted += 1
            else:
                break
        assert admitted < 2000, "a rotating session id bypassed the limiter entirely"

    async def test_bucket_store_is_bounded(self, config):
        limiter = TokenBucketRateLimiter(config, redis_client=None)
        for i in range(limiter.MAX_TRACKED_BUCKETS * 2):
            await limiter.check_and_consume(f"session-{i}")
        assert len(limiter._buckets) <= limiter.MAX_TRACKED_BUCKETS
