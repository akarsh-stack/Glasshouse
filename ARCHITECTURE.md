# Glasshouse Architecture

This document is written to be read aloud in an interview. Each section answers
the same two questions: *why does this layer exist* and *what breaks without it*.

## The pipeline, layer by layer

### Rate limiter (token bucket, `services/rate_limiter.py`)

**Why:** every query downstream of this point costs real money (an LLM call) or
real CPU (an embedding). The rate limiter is the only layer allowed to say "no"
before any of that is spent. It's a per-session token bucket — 100 token capacity,
refilling at 10 tokens/second — executed as an atomic Redis Lua script so two
concurrent requests can't both spend the last token. Why a bucket and not a fixed
window: [ADR-003](docs/adr/003-token-bucket-rate-limiting.md).

**Without it:** one misbehaving client (or my own load test) monetizes itself
directly into my Anthropic bill, and a burst of traffic degrades everyone instead
of just the burster. Rejected requests get an explicit `429` error event with a
computed `retry_after`, so well-behaved clients know exactly when to come back.

### Embedding service (micro-batched, `services/embedding.py`)

**Why:** embedding models are throughput-optimized — encoding 16 texts in one call
costs barely more than encoding one. Instead of embedding each request as it
arrives, requests enqueue a future and a background worker flushes the queue every
30 ms as a single batch. Under load, N concurrent queries pay ~1 model invocation
plus at most 30 ms of added latency; when idle, the cost is just the 30 ms window.

**Without it:** at 20 concurrent requests, the local model runs 20 serialized
`encode()` calls in the executor; batch them and it's one. This is the classic
throughput-for-latency trade, and 30 ms is invisible next to a 1.5 s LLM call.

The model is `all-MiniLM-L6-v2` (384-dim), run locally by default through
onnxruntime rather than PyTorch — same model, ~80 MB instead of ~2.5 GB of
dependencies. `sentence-transformers` and OpenAI are both selectable providers.
See [ADR-005](docs/adr/005-onnx-embeddings.md).

### Vector store (Chroma behind a Protocol, `services/vector_store.py`)

**Why:** retrieval is what makes this RAG rather than a chatbot. Chunks live in an
embedded ChromaDB collection (cosine space, persisted to disk) — zero external
infrastructure, so a stranger can clone and run. Crucially, the code depends on a
three-method `VectorStore` Protocol (`upsert`, `query`, `delete_by_document`), not
on Chroma. See [ADR-001](docs/adr/001-chromadb-behind-a-protocol.md).

**Without it:** the LLM answers from its training data instead of your documents.
Glasshouse treats this as a degraded mode, not a crash: if retrieval throws, the
query proceeds with zero context chunks and the trace shows it.

### Chunking and retrieval gating (`chunkers/structural.py`, `services/retrieval.py`)

**Why:** this is where the first version was actually broken, and it is the most
useful thing in the codebase to talk about. Fixed 220-word windows plus an
absolute 0.3 score threshold returned **zero chunks for a question the corpus
plainly answered**. Two stacked defects, each sufficient alone:

- **The threshold was above the real score range.** Question→passage cosine for a
  *correct* match measures 0.19–0.61 here, not 0.7+. A question and the passage
  answering it are different registers, not paraphrases, so a bi-encoder scores
  that pairing low. 0.3 sat inside the correct-match range and deleted true
  positives — the failing query's best chunk scored 0.240 and was dropped.
- **Fixed-width chunks are topic grab-bags.** Windows cut where the counter runs
  out, so chunks straddle sections. A chunk covering altitude, power *and*
  attitude control won a **water recovery** query at 0.447, beating the chunk that
  actually discussed water. A multi-topic chunk's embedding is the average of its
  topics and points at none of them: it matches many queries weakly and none
  strongly, which is precisely how it outranks the specific right answer.

**The fix:** split on structure first, size second — never merge across a heading,
and prepend the governing heading to every chunk it covers. Then gate retrieval
**relative to the top hit** (keep chunks within 55% of the best score) rather than
against a fixed floor, because the signal is the *gap* between the top hit and the
rest, not the absolute number. A near-zero absolute floor (0.08) is retained only
to reject genuine noise. PDFs get an extra heading heuristic, since `pypdf`
returns hard-wrapped lines with no markup: a heading is short, unpunctuated, and
substantially shorter than the document's median line.

**Result:** 0.240-on-the-wrong-chunk became **0.605 on the correct chunk**; the
sample markdown produces 6 single-topic chunks instead of 3 grab-bags, and the
sample PDF 3 instead of 1. See
[ADR-006](docs/adr/006-chunking-and-relative-score-gating.md).

**Without it:** the system holds the answer and says it doesn't know — the worst
failure mode a RAG system has, because it looks like a model problem and is
actually an indexing problem.

### Two-tier cache (`services/cache.py`)

**Why each tier exists:**

- **Exact tier** — SHA-256 of the lowercased, whitespace-collapsed query, stored in
  Redis with a 1-hour TTL (in-memory LRU of 256 entries when Redis is down). Repeat
  questions are free: no embedding comparison, no LLM, no cost. Exact matching is
  O(1) and can never return a wrong answer, so it runs first.
- **Semantic tier** — cached query embeddings compared by cosine similarity; a hit
  requires ≥ 0.80 (configurable) **and** matching lexical polarity. This is what
  catches "What are the key findings?" after someone already asked "Summarize the
  key findings." Paraphrases dominate real traffic; exact matching alone misses
  almost all of them.

  The threshold is measured, not guessed, and the intuitive value was wrong. This
  tier shipped at 0.95 and never fired once — measured same-intent paraphrases run
  0.67–0.96, so 0.95 rejects most genuine repeats. 0.80 sits at twice the top of
  the related-but-distinct band (0.35–0.40) and catches natural rewordings.

  Negation is handled separately, because it cannot be handled by a threshold: a
  negated query scores **0.825** against its affirmative form — above two thirds of
  the paraphrase band. Negation is a one-token change with a total semantic
  inversion, and a bi-encoder barely registers it. So the embedding decides topic
  and a small lexical negator check decides polarity; a candidate whose polarity
  differs is skipped however close the vectors are. See
  [ADR-002](docs/adr/002-semantic-cache-tier.md).

Both tiers are bounded (TTL expiry plus LRU / a 512-entry cap on the semantic
store), so stale answers age out and memory can't grow without limit.

**Without it:** every paraphrase of a popular question is a fresh LLM call. At a
40% hit rate, the cache is deleting 40% of the platform's marginal cost and
turning ~1.5 s answers into ~10 ms answers.

### Model router with fallback (`services/router.py`)

**Why:** not every query deserves Opus. The router maps queries to tiers — `fast`
(claude-haiku-4-5), `quality` (claude-sonnet-5), `deep` (claude-opus-5) — by
user hint or a simple length heuristic. When a tier fails, it walks the remaining
tiers in order and sets `fallback_triggered` on the trace, so degradation is
*surfaced*, never silent: the Generate node pulses in the UI and the receipt names
the model that actually answered.

**Without it:** either everything runs on the most expensive model (10–60x cost
for short factual queries), or a single model outage takes the whole product down.

### LLM service with circuit breaker (`services/llm.py`)

**Why:** each tier has its own circuit breaker — 3 consecutive failures open it,
and it stays open for a 30-second cooldown. While open, calls to that tier fail
instantly, which does two things: the router falls back immediately instead of
waiting out a timeout, and the struggling upstream gets breathing room instead of
a retry storm.

**Without it:** during a provider incident, every request eats a full timeout
before failing over, latency explodes, and my own retries make the provider's
incident worse.

### Observability (`services/observability.py`)

**Why:** this is the product. Every request gets a `RequestTrace` — per-stage
milliseconds, cache status, model used, fallback flag, tokens, cost, retrieved
chunk IDs — persisted to SQLite. The metrics endpoint aggregates them into
p50/p95/p99 latency, cache hit rate, error rate, cost, and model breakdown.

**Two populations, deliberately separate.** `total_requests` counts *arrivals*;
every rate is computed over *admitted* requests (`served_requests`). A request the
limiter rejected did no work — it never embedded, never checked the cache, never
called a model — so it has no latency, no cache verdict, and no error to
contribute. Mixing the two is not a rounding detail: a 220-request burst reported
**p50 = 0 ms next to p95 = 36 s**, because 117 rejections each contributed 0 ms and
took over the median. A platform shedding load looked instantaneous. The rule is
that a shed request appears in the count and in `rate_limited_count`, and nowhere
else.

**Without it:** you cannot answer "why was that query slow?" or "what did today
cost?" — which are the first two questions anyone operating a RAG system asks.

## Worked capacity estimate

Assume a modest production target: **100K daily active users, ~4 queries per user
per day.**

1. **Daily volume:** 100,000 × 4 = **400K queries/day**.
2. **Average QPS:** 400,000 / 86,400 s ≈ **4.6 QPS**.
3. **Peak factor:** traffic isn't flat — business-hours products concentrate load,
   typically 5–8x the daily average. 4.6 × 5 ≈ 23, 4.6 × 8 ≈ 37 → call it
   **~25–37 QPS at peak**.
4. **What dominates:** the LLM call, at p95 ≈ 1.5 s. Everything else in the
   pipeline (embed ~10–30 ms micro-batched, Chroma query ~5–20 ms, cache check
   ~1–10 ms) is noise by comparison. So the constraint isn't CPU — it's
   **concurrent in-flight LLM calls**.
5. **Concurrency (Little's Law):** concurrency ≈ arrival rate × time in system.
   At peak: 25–37 QPS × 1.5 s ≈ **37–56 concurrent requests** if every query hit
   the LLM.
6. **Cache absorption:** at a 40% cache hit rate, only 60% of queries reach the
   LLM: 0.6 × (25–37) × 1.5 s ≈ **14–22 concurrent LLM calls** — and cache hits
   return in ~10 ms, so they contribute essentially zero concurrency.

Conclusions from the arithmetic: a single async FastAPI process handles this
comfortably because concurrent LLM calls are just awaiting sockets, not burning
CPU; the numbers to actually watch are the Anthropic rate limit (requests and
tokens per minute against those 14–22 concurrent calls) and the cache hit rate,
because every point of hit rate directly buys headroom and cuts cost. At this
scale, the bottleneck is the wallet, not the hardware.

## Scaling the vector store past a single node

Embedded Chroma is the right call up to roughly a million vectors on one node
(see [ADR-001](docs/adr/001-chromadb-behind-a-protocol.md)). Past that, in order:

1. **Replication first** — RAG is read-heavy (every query is a search; writes only
   happen at ingest). Read replicas multiply query throughput cheaply and cover
   the common case.
2. **Sharding by document or tenant** — chunks have a natural partition key
   (`document_id`, or tenant in a multi-tenant deployment). Route queries to the
   shard that owns the relevant corpus; there is rarely a need to fan out across
   all shards.
3. **Swap the engine** — when you need multi-node, quantization, or
   metadata-filtered search at scale, move to Qdrant or pgvector. Because every
   caller depends on the `VectorStore` Protocol and not on Chroma, this is a new
   ~70-line adapter class and a config change, not a refactor. The
   `docker-compose.yml` already carries a Qdrant service behind a profile for
   exactly this experiment.

## When to add hybrid (vector + BM25) search

Dense retrieval fails predictably on queries where the *literal token* matters
more than the meaning:

- **Exact identifiers** — invoice numbers, error codes, SKUs ("find INV-2024-0113").
  Embeddings blur these into "some invoice-ish string".
- **Rare terms** — a name or term that appears once in the corpus gets no
  statistical signal in a 384-dim embedding, but BM25 nails it on IDF alone.
- **Out-of-vocabulary jargon** — internal project names and acronyms the embedding
  model never saw at training time.

The upgrade path: run BM25 alongside vector search and merge with reciprocal rank
fusion. It slots in behind the same retrieval orchestrator, and the trace would
show both branches' latency — in keeping with the whole point of the project.

## Why the fallback chain exists

Glasshouse depends on third parties at three points: Redis, the vector store, and
the Anthropic API. Each dependency has a designed answer to "what if it's gone",
decided at startup or per-request — never by crashing. The principle is that
**degradation is surfaced, not hidden**: the trace records `fallback_triggered`,
the cache badge says which tier answered, and the receipt names the actual model.
A demo where you can `docker stop redis` mid-session and the app keeps working —
while *telling you* it switched to in-memory — is worth more than a demo that
never fails.

## Failure modes

| Failure | Detection | Behavior | Surfaced as |
|---|---|---|---|
| Redis down | Startup ping fails, or per-call exception | Cache falls back to in-memory LRU (256 entries); rate limiter falls back to in-memory buckets | Log warning; functionality intact, cache/limits become per-process |
| Vector store down / retrieval error | Exception in `RetrievalOrchestrator.retrieve` | Query continues with **zero context chunks** — no-context chat instead of an error page | Empty chunk panel; trace shows retrieval stage failed |
| Primary model down | Streaming error → circuit breaker (opens after 3 failures, 30 s cooldown) | Router walks remaining tiers (`quality` → `fast` → `deep` order preserved) | `fallback_triggered: true` in trace; Generate node pulses; receipt names the substitute model |
| All model tiers down | Every tier raises | Request fails with an explicit error event | SSE `error` event with the message; error rate on Ops dashboard |
| Rate limit exceeded | Token bucket empty for session | Request rejected before any work is done | `429` error event with computed `retry_after` seconds |
| Embedding failure during cache check | Exception in `embed_one` | Cache is skipped (no embedding to compare); query proceeds to LLM | Cache stage shows miss |

## Decision records

The four decisions most likely to be challenged, each written up with the
alternatives that were rejected and why:

| ADR | Decision |
|---|---|
| [ADR-001](docs/adr/001-chromadb-behind-a-protocol.md) | Embedded ChromaDB behind a `VectorStore` Protocol |
| [ADR-002](docs/adr/002-semantic-cache-tier.md) | A semantic cache tier, not exact-match alone |
| [ADR-003](docs/adr/003-token-bucket-rate-limiting.md) | Token bucket, not fixed window, for rate limiting |
| [ADR-004](docs/adr/004-sse-over-websockets.md) | Server-Sent Events for the query stream |
| [ADR-005](docs/adr/005-onnx-embeddings.md) | ONNX runtime as the default embedding backend |
| [ADR-006](docs/adr/006-chunking-and-relative-score-gating.md) | Structural chunking and relative score gating |
