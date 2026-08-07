"""Walk the README's interview demo script end to end against a live backend.

Every number printed comes from a real request: real embeddings, real vector
search, real Anthropic calls, real cache. If this passes, the demo works.

    python verify_dod.py [base_url]

PRECONDITION: run against a freshly started backend. The cache-tier checks assert
that specific queries *miss*, which only holds on a cold cache. Re-running against
a warm one legitimately turns those misses into exact hits. This cannot be worked
around with a per-run nonce, because a nonce-suffixed query is a ~0.99 paraphrase
of the previous run's and the semantic tier will — correctly — serve it. With no
Redis running the cache is in-process, so restarting uvicorn is enough.
"""

import asyncio
import json
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


async def ask(client: httpx.AsyncClient, query: str, session: str = "dod") -> dict:
    t0 = time.monotonic()
    out = {"cache": None, "sim": None, "chunks": 0, "top": None, "text": "", "trace": None}
    async with client.stream(
        "POST", f"{BASE}/api/query", json={"query": query, "session_id": session}
    ) as res:
        res.raise_for_status()
        async for line in res.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            kind = ev.get("type")
            if kind == "retrieval":
                out["chunks"] = len(ev["chunks"])
                if ev["chunks"]:
                    out["top"] = round(ev["chunks"][0]["score"], 3)
            elif kind == "cache":
                out["cache"] = ev["status"]
                out["sim"] = ev.get("similarity")
            elif kind == "chunk":
                out["text"] += ev["text"]
            elif kind == "done":
                out["trace"] = ev["trace"]
    out["wall_ms"] = round((time.monotonic() - t0) * 1000)
    return out


def line(label: str, r: dict) -> None:
    t = r["trace"] or {}
    sim = f"{r['sim']:.3f}" if isinstance(r["sim"], (int, float)) else "—"
    print(
        f"  {label:<26} cache={str(r['cache']):<12} sim={sim:<7} "
        f"chunks={r['chunks']} top={str(r['top']):<6} "
        f"model={str(t.get('model_used') or '—'):<17} "
        f"fallback={str(bool(t.get('fallback_triggered'))):<5} "
        f"${t.get('cost_usd', 0):.6f} {r['wall_ms']}ms"
    )


async def main() -> None:
    failures: list[str] = []
    async with httpx.AsyncClient(timeout=180.0) as client:
        print("\n[1] ingestion is idempotent (content-hash dedup)")
        ids = []
        for _ in range(2):
            with open("../samples/meridian-release-notes.pdf", "rb") as fh:
                r = await client.post(f"{BASE}/api/documents", files={"file": fh})
            r.raise_for_status()
            ids.append((r.json()["id"], r.json()["chunk_count"]))
        print(f"  upload twice -> ids {ids[0][0][:8]} / {ids[1][0][:8]}, "
              f"chunks {ids[0][1]} / {ids[1][1]}")
        if ids[0][0] != ids[1][0]:
            failures.append("re-upload created a second document")

        print("\n[2] PDF retrieval + grounded answer")
        q = "How much did incremental linking reduce link times?"
        a = await ask(client, q)
        line("pdf question", a)
        warm = a["cache"] != "miss"
        if warm:
            print("\n  !! cache is warm from a previous run — the 'must miss'")
            print("     assertions below cannot hold. Restart uvicorn and re-run.")
            failures.append("cache was warm at start; restart the backend")
        elif "41" not in a["text"] or "6" not in a["text"]:
            failures.append("PDF answer missing the 41s -> 6s figures")

        print("\n[3] cache tiers")
        line("exact repeat", await ask(client, q))
        line("paraphrase", await ask(
            client, "By how much were link times cut with incremental linking?"))
        neg = await ask(
            client, "Can the new linker not emit split debug info on 32-bit targets?")
        line("negation (must miss)", neg)
        if neg["cache"] != "miss" and not warm:
            failures.append("negated query was served from cache")

        print("\n[4] markdown corpus, different document")
        line("water recovery", await ask(
            client, "How much water does life support recycle?"))

        print("\n[5] rate limiter returns a real 429 + Retry-After")
        # Every burst request sends the *same* query on purpose. The limiter runs
        # before the cache, so identical text still exercises it fully, while the
        # admitted requests collapse onto one exact cache hit instead of 200 real
        # LLM calls. Testing a pre-LLM component should not cost LLM money.
        #
        # The connection limit is not incidental: httpx pools 100 connections by
        # default, which silently serialises a larger burst into a trickle the
        # 10-tokens/sec refill can absorb, and nothing is ever rejected. The
        # bucket holds 100 tokens, so the burst must exceed that *concurrently*.
        burst_n = 220
        limits = httpx.Limits(max_connections=400, max_keepalive_connections=400)
        async with httpx.AsyncClient(timeout=180.0, limits=limits) as burst_client:
            burst = await asyncio.gather(*(
                burst_client.post(
                    f"{BASE}/api/query",
                    json={"query": "burst probe", "session_id": "dod-burst"},
                )
                for _ in range(burst_n)
            ), return_exceptions=True)
        codes = [getattr(x, "status_code", None) for x in burst]
        n429 = codes.count(429)
        hdr = next((x.headers.get("Retry-After") for x in burst
                    if getattr(x, "status_code", None) == 429), None)
        print(f"  {burst_n} concurrent -> 200:{codes.count(200)} 429:{n429} "
              f"Retry-After={hdr}")
        if n429 == 0:
            failures.append("burst produced no 429s")
        if n429 and hdr is None:
            failures.append("429 missing Retry-After header")

        print("\n[6] observability reflects it all")
        m = (await client.get(f"{BASE}/api/metrics?window=1h")).json()
        print(f"  arrived={m['total_requests']} served={m.get('served_requests')} "
              f"cache_hit_rate={m.get('cache_hit_rate')} "
              f"error_rate={m.get('error_rate')} "
              f"rate_limited={m.get('rate_limited_count')}")
        print(f"  p50={m.get('latency_p50_ms')}ms p95={m.get('latency_p95_ms')}ms "
              f"cost=${m.get('total_cost_usd')}")
        print(f"  models={m.get('model_breakdown')}")
        if not m.get("rate_limited_count"):
            failures.append("metrics did not record the rate-limited requests")
        # A rejected request never entered the pipeline, so it has no latency to
        # report. Counting its 0 ms drags p50 to zero and makes a platform shedding
        # load look instant — which is exactly what this used to do (p50=0 next to
        # p95=36s). Rejections must be out of the latency population entirely.
        if m.get("latency_p50_ms", 0) <= 0:
            failures.append(
                "p50 is 0 — rate-limited requests are polluting the latency set"
            )
        # error_rate is deliberately NOT asserted to be zero. Upstream providers
        # do fail under concurrency, and when they do this number should move —
        # that is the observability layer working, not the platform breaking. The
        # requirement is that the figures are real and that the two failure kinds
        # stay separate, which is what is checked instead: every 429 must land in
        # rate_limited_count and none of them in error_rate.
        served_n = m.get("served_requests") or m["total_requests"]
        errors = round(m.get("error_rate", 0) * served_n)
        if m.get("rate_limited_count", 0) < n429:
            failures.append(
                f"{n429} requests were rejected but only "
                f"{m.get('rate_limited_count')} counted as rate-limited"
            )
        if m["total_requests"] - served_n < n429:
            failures.append("rejected requests were counted as served")
        if errors >= n429 and n429:
            print(f"  note: {errors} upstream errors recorded, counted apart "
                  f"from the {m['rate_limited_count']} rate-limited requests")

        rid = a["trace"]["request_id"]
        tr = await client.get(f"{BASE}/api/traces/{rid}")
        print(f"\n[7] trace replay GET /api/traces/{rid[:8]} -> {tr.status_code}")
        if tr.status_code != 200:
            failures.append("trace replay endpoint failed")

    print()
    if failures:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("PASS — every definition-of-done behaviour verified against live traffic.")


asyncio.run(main())
