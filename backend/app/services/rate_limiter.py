import logging
import time
from typing import Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Buckets are checked and debited together, all-or-nothing, in one round trip.
#
# The script returns the *pre-debit* budget of the tightest bucket alongside the
# verdict. Without that number Python cannot compute a real `Retry-After` — the
# previous version returned `requested / refill_rate`, a constant, so every
# rejection claimed the same wait no matter how far over budget the caller was.
#
# Token counts cross the boundary as integer milli-tokens because Lua->Redis
# conversion truncates floats to integers, which would round 0.4 tokens to 0.
LUA_SCRIPT = """
local now = tonumber(ARGV[1])
local requested = tonumber(ARGV[2])
local n = #KEYS

local budgets = {}
local allowed = 1

for i = 1, n do
    local capacity = tonumber(ARGV[2 + (i - 1) * 2 + 1])
    local refill_rate = tonumber(ARGV[2 + (i - 1) * 2 + 2])
    local data = redis.call('HMGET', KEYS[i], 'tokens', 'last_refill')
    local tokens = tonumber(data[1]) or capacity
    local last_refill = tonumber(data[2]) or now

    tokens = math.min(capacity, tokens + (now - last_refill) * refill_rate)
    budgets[i] = tokens
    if tokens < requested then
        allowed = 0
    end
end

local tightest = -1
for i = 1, n do
    -- Debit only if every bucket could pay; a partial debit would charge the
    -- caller for a request that was refused.
    local remaining = budgets[i]
    if allowed == 1 then
        remaining = remaining - requested
    end
    redis.call('HMSET', KEYS[i], 'tokens', remaining, 'last_refill', now)
    redis.call('EXPIRE', KEYS[i], 3600)
    if tightest < 0 or budgets[i] < tightest then
        tightest = budgets[i]
    end
end

return {allowed, math.floor(tightest * 1000)}
"""


def retry_after_for(remaining: float, requested: int, refill_rate: float) -> float:
    """Seconds until `requested` tokens exist, given `remaining` right now."""
    if refill_rate <= 0:
        return 0.0
    deficit = max(0.0, requested - remaining)
    return round(deficit / refill_rate, 2)


class TokenBucketRateLimiter:
    """Per-session and per-IP token buckets, both of which must have budget.

    Two dimensions because either alone is trivially defeated. `session_id` is
    client-supplied — the frontend mints a fresh UUID on every page load — so a
    session-only limit is bypassed by rotating it. An IP-only limit, meanwhile,
    lumps everyone behind a NAT into one bucket. The session bucket is the tight
    per-user limit; the IP bucket is a looser backstop that rotation can't shed.

    Note that the IP is taken from the socket, not from `X-Forwarded-For`:
    trusting a client-settable header for the key would reintroduce exactly the
    bypass this is here to close. Behind a proxy, configure the proxy's real-IP
    handling and read it from a header you control.
    """

    #: Distinct buckets held in the no-Redis fallback. The Redis path has
    #: `EXPIRE`; this is the equivalent ceiling for a plain process, so an
    #: attacker cycling keys can't grow the dict without bound.
    MAX_TRACKED_BUCKETS = 10_000
    BUCKET_TTL_S = 3600

    def __init__(self, config, redis_client=None):
        self.config = config
        self.redis = redis_client
        self._buckets: TTLCache = TTLCache(
            maxsize=self.MAX_TRACKED_BUCKETS, ttl=self.BUCKET_TTL_S
        )

    def _dimensions(self, session_id: str, client_ip: Optional[str]) -> list[tuple[str, int, float]]:
        """(key, capacity, refill_rate) for every bucket this request spends from."""
        dims = [(
            f"gh:ratelimit:session:{session_id}",
            self.config.RATE_LIMIT_TOKENS,
            self.config.RATE_LIMIT_REFILL_RATE,
        )]
        if client_ip:
            dims.append((
                f"gh:ratelimit:ip:{client_ip}",
                self.config.RATE_LIMIT_IP_TOKENS,
                self.config.RATE_LIMIT_IP_REFILL_RATE,
            ))
        return dims

    async def check_and_consume(
        self,
        session_id: str,
        tokens: int = 1,
        client_ip: Optional[str] = None,
    ) -> dict:
        dims = self._dimensions(session_id, client_ip)

        if self.redis:
            try:
                argv: list = [time.time(), tokens]
                for _, capacity, refill_rate in dims:
                    argv.extend([capacity, refill_rate])
                allowed, tightest_milli = await self.redis.eval(
                    LUA_SCRIPT, len(dims), *[key for key, _, _ in dims], *argv
                )
                if int(allowed) == 1:
                    return {"allowed": True, "retry_after": None}
                # The binding constraint may be either bucket, so refill at the
                # slowest rate in play — reporting the faster one would invite a
                # retry that is rejected again.
                slowest = min(refill for _, _, refill in dims)
                return {
                    "allowed": False,
                    "retry_after": retry_after_for(int(tightest_milli) / 1000.0, tokens, slowest),
                }
            except Exception as e:
                logger.warning(f"Redis rate limit error: {e}, falling back to in-memory")

        return self._check_in_memory(dims, tokens)

    def _check_in_memory(self, dims: list[tuple[str, int, float]], tokens: int) -> dict:
        now = time.monotonic()

        # Refill every bucket first, then decide, so a rejection doesn't debit
        # the buckets that did have budget.
        budgets: list[tuple[str, dict, float]] = []
        for key, capacity, refill_rate in dims:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = {"tokens": float(capacity), "last_refill": now}
            elapsed = now - bucket["last_refill"]
            bucket["tokens"] = min(capacity, bucket["tokens"] + elapsed * refill_rate)
            bucket["last_refill"] = now
            self._buckets[key] = bucket
            budgets.append((key, bucket, refill_rate))

        if all(bucket["tokens"] >= tokens for _, bucket, _ in budgets):
            for _, bucket, _ in budgets:
                bucket["tokens"] -= tokens
            return {"allowed": True, "retry_after": None}

        tightest = min(bucket["tokens"] for _, bucket, _ in budgets)
        slowest = min(refill for _, _, refill in budgets)
        return {"allowed": False, "retry_after": retry_after_for(tightest, tokens, slowest)}
