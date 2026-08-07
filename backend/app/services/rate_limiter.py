import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local tokens_requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1]) or capacity
local last_refill = tonumber(data[2]) or now

local elapsed = now - last_refill
local refilled = elapsed * refill_rate
tokens = math.min(capacity, tokens + refilled)

if tokens >= tokens_requested then
    tokens = tokens - tokens_requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 0
end
"""


class TokenBucketRateLimiter:
    def __init__(self, config, redis_client=None):
        self.config = config
        self.redis = redis_client
        self._buckets: dict[str, dict] = {}

    async def check_and_consume(self, session_id: str, tokens: int = 1) -> dict:
        capacity = self.config.RATE_LIMIT_TOKENS
        refill_rate = self.config.RATE_LIMIT_REFILL_RATE
        now = time.monotonic()

        if self.redis:
            try:
                result = await self.redis.eval(
                    LUA_SCRIPT, 1,
                    f"gh:ratelimit:{session_id}",
                    capacity, refill_rate, tokens, time.time()
                )
                if result == 1:
                    return {"allowed": True, "retry_after": None}
                else:
                    return {"allowed": False, "retry_after": round(tokens / refill_rate, 2)}
            except Exception as e:
                logger.warning(f"Redis rate limit error: {e}, falling back to in-memory")

        # in-memory fallback
        bucket = self._buckets.get(session_id)
        if bucket is None:
            bucket = {"tokens": float(capacity), "last_refill": now}
            self._buckets[session_id] = bucket

        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(capacity, bucket["tokens"] + elapsed * refill_rate)
        bucket["last_refill"] = now

        if bucket["tokens"] >= tokens:
            bucket["tokens"] -= tokens
            return {"allowed": True, "retry_after": None}
        else:
            retry_after = round((tokens - bucket["tokens"]) / refill_rate, 2)
            return {"allowed": False, "retry_after": retry_after}
