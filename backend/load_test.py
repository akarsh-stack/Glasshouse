"""Sustained load generator for Glasshouse.

Drives real traffic through the real pipeline — real embeddings, real vector
search, real cache, real LLM calls — so the Ops dashboard fills with numbers that
actually mean something. Nothing here is mocked.

    python load_test.py --concurrency 20 --duration 30

Client-side stats are reported alongside a pointer to /api/metrics, because the
two are measured differently and the gap is the interesting part: this script
sees wall-clock latency including queueing, while the server's percentiles cover
in-handler time only.

Costs real money on cache misses. Defaults are deliberately modest.
"""

import argparse
import asyncio
import json
import time
from collections import Counter

import httpx

QUERIES = [
    "What altitude does the station maintain?",
    "How much power do the solar arrays generate?",
    "How is attitude controlled?",
    "How is waste heat rejected?",
    "How much water does life support recycle?",
    "When are conjunction assessments screened?",
    "What did incremental linking improve?",
    "Are builds reproducible?",
    "What limitation affects 32-bit targets?",
    "What do the diagnostics now include?",
]


async def worker(
    client: httpx.AsyncClient,
    base: str,
    session: str,
    deadline: float,
    counter: Counter,
    latencies: list[float],
    index: int,
) -> None:
    i = index
    while time.monotonic() < deadline:
        query = QUERIES[i % len(QUERIES)]
        i += 1
        t0 = time.monotonic()
        try:
            async with client.stream(
                "POST",
                f"{base}/api/query",
                json={"query": query, "session_id": session},
            ) as res:
                if res.status_code == 429:
                    await res.aread()
                    counter["rate_limited"] += 1
                    # Honour the limiter rather than spinning against it; a load
                    # generator that ignores Retry-After measures its own retry
                    # loop instead of the server.
                    await asyncio.sleep(float(res.headers.get("Retry-After", 1)))
                    continue
                if res.status_code != 200:
                    await res.aread()
                    counter[f"http_{res.status_code}"] += 1
                    continue

                cache_status = None
                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "cache":
                        cache_status = event.get("status")
                    elif event.get("type") == "error":
                        counter["stream_error"] += 1

                counter["ok"] += 1
                counter[cache_status or "unknown"] += 1
                latencies.append((time.monotonic() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            counter[f"exception:{type(e).__name__}"] += 1


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, int(round((p / 100) * len(ordered) + 0.5)) - 1)
    return ordered[max(0, k)]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--duration", type=int, default=20, help="seconds")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument(
        "--session",
        default="load-test",
        help="Shared session id. One bucket for all workers, so the rate limiter "
        "is genuinely exercised; pass a unique value per worker to bypass it.",
    )
    args = ap.parse_args()

    counter: Counter = Counter()
    latencies: list[float] = []
    deadline = time.monotonic() + args.duration

    print(f"{args.concurrency} workers for {args.duration}s against {args.base}")
    # Default pool is 100 connections, which silently serialises higher
    # concurrency and understates what the server actually handled.
    limits = httpx.Limits(
        max_connections=max(100, args.concurrency * 2),
        max_keepalive_connections=max(100, args.concurrency * 2),
    )
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
        await asyncio.gather(
            *(
                worker(client, args.base, args.session, deadline, counter, latencies, i)
                for i in range(args.concurrency)
            )
        )
    elapsed = time.monotonic() - started

    ok = counter["ok"]
    print()
    print(f"completed        {ok} in {elapsed:.1f}s  ({ok / elapsed:.2f} req/s)")
    print(f"rate limited     {counter['rate_limited']} (429, honoured Retry-After)")
    print(
        "cache            "
        f"miss={counter['miss']} exact={counter['hit_exact']} semantic={counter['hit_semantic']}"
    )
    if latencies:
        print(
            "client latency   "
            f"p50={percentile(latencies, 50):.0f}ms "
            f"p95={percentile(latencies, 95):.0f}ms "
            f"p99={percentile(latencies, 99):.0f}ms"
        )
    other = {
        k: v
        for k, v in counter.items()
        if k
        not in {"ok", "rate_limited", "miss", "hit_exact", "hit_semantic", "unknown"}
    }
    if other:
        print(f"other            {dict(other)}")
    print()
    print(f"server-side view: curl '{args.base}/api/metrics?window=1h'")


if __name__ == "__main__":
    asyncio.run(main())
