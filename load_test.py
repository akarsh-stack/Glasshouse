import asyncio
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

SAMPLE_QUERIES = [
    "What is the main topic of the documents?",
    "Summarize the key findings.",
    "What are the most important conclusions?",
    "Explain the methodology used.",
    "What data sources were referenced?",
    "What are the limitations mentioned?",
    "How does this compare to previous work?",
    "What recommendations are provided?",
    "What future work is suggested?",
    "What are the core assumptions made?",
]


async def run_query(client: httpx.AsyncClient, url: str, query: str) -> dict:
    start = time.monotonic()
    try:
        async with client.stream(
            "POST",
            f"{url}/api/query",
            json={"query": query, "session_id": "load_test"},
            timeout=60.0,
        ) as resp:
            if resp.status_code != 200:
                return {"ok": False, "latency_ms": (time.monotonic() - start) * 1000}
            async for _ in resp.aiter_lines():
                pass
        return {"ok": True, "latency_ms": (time.monotonic() - start) * 1000}
    except Exception as e:
        return {"ok": False, "latency_ms": (time.monotonic() - start) * 1000, "error": str(e)}


async def load_test(url: str, concurrency: int, duration: int):
    results = []
    deadline = time.monotonic() + duration
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(query: str):
        async with semaphore:
            async with httpx.AsyncClient() as client:
                r = await run_query(client, url, query)
                results.append(r)

    tasks = []
    i = 0
    while time.monotonic() < deadline:
        query = SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)]
        tasks.append(asyncio.create_task(worker(query)))
        i += 1
        await asyncio.sleep(0.05)

    await asyncio.gather(*tasks, return_exceptions=True)

    latencies = sorted(r["latency_ms"] for r in results)
    n = len(latencies)
    errors = sum(1 for r in results if not r["ok"])

    def pct(p):
        if not latencies:
            return 0
        return latencies[min(int(n * p / 100), n - 1)]

    print(f"\n=== Load Test Results ===")
    print(f"Total requests : {n}")
    print(f"Errors         : {errors} ({100*errors/n:.1f}%)" if n else "No requests")
    print(f"Req/sec        : {n/duration:.2f}")
    print(f"p50 latency    : {pct(50):.0f}ms")
    print(f"p95 latency    : {pct(95):.0f}ms")
    print(f"p99 latency    : {pct(99):.0f}ms")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=int, default=30)
    args = parser.parse_args()

    asyncio.run(load_test(args.url, args.concurrency, args.duration))
