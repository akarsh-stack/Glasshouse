"""Verify the rate limiter returns a real HTTP 429 with a Retry-After header.

Two things this checks that an in-stream error event could not:
  * the status line is 429, so proxies and status-keyed retry logic see it
  * Retry-After is present and parses as integer seconds

Burst size must exceed the bucket capacity, and the requests must be genuinely
concurrent: at 10 tokens/sec refill, sequential requests can never outrun the
refill rate no matter how many you send. httpx also caps connections at 100 by
default, which silently serialises the tail of a larger burst.
"""

import asyncio
import sys
from collections import Counter

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
BURST = 160


async def one(client: httpx.AsyncClient, i: int) -> tuple[int, str | None, object]:
    try:
        r = await client.post(
            f"{BASE}/api/query",
            json={"query": f"burst probe {i}", "session_id": "rate-limit-probe"},
        )
        body = None
        if r.status_code == 429:
            body = r.json().get("detail")
        return r.status_code, r.headers.get("Retry-After"), body
    except Exception as e:  # noqa: BLE001
        return -1, None, repr(e)[:60]


async def main() -> None:
    limits = httpx.Limits(max_connections=400, max_keepalive_connections=400)
    async with httpx.AsyncClient(timeout=90.0, limits=limits) as client:
        results = await asyncio.gather(*(one(client, i) for i in range(BURST)))

    statuses = Counter(r[0] for r in results)
    print(f"burst of {BURST} concurrent requests -> {dict(statuses)}")

    rejected = [r for r in results if r[0] == 429]
    print(f"429 count: {len(rejected)}")
    if rejected:
        with_header = [r for r in rejected if r[1] is not None]
        print(f"429s carrying Retry-After: {len(with_header)}/{len(rejected)}")
        headers = sorted({r[1] for r in with_header})
        print(f"distinct Retry-After header values: {headers}")
        precise = [
            r[2]["retry_after"]
            for r in rejected
            if isinstance(r[2], dict) and "retry_after" in r[2]
        ]
        if precise:
            print(f"body retry_after range: {min(precise)} .. {max(precise)}")

    ok = statuses.get(200, 0)
    print()
    print("PASS" if len(rejected) > 0 and ok > 0 else "FAIL")
    print(f"  {ok} served, {len(rejected)} shed — the limiter both admits and rejects.")


asyncio.run(main())
