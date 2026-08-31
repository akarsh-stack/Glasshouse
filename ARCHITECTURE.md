# Glasshouse Architecture

This document is written to be read aloud in an interview. Each section answers
the same two questions: *why does this layer exist* and *what breaks without it*.

## The pipeline, layer by layer

### Rate limiter (token bucket, `services/rate_limiter.py`)

**Why:** every query downstream of this point costs real money (an LLM call) or
real CPU (an embedding). The rate limiter is the only layer allowed to say "no"
before any of that is spent. It's a token bucket — 100 token capacity, refilling
at 10 tokens/second — executed as an atomic Redis Lua script so two concurrent
requests can't both spend the last token. Why a bucket and not a fixed window:
[ADR-003](docs/adr/003-token-bucket-rate-limiting.md).

**Two dimensions, because either alone is defeated.** The tight bucket is keyed
on `session_id` — but that comes from the client, and the frontend mints a fresh
UUID on every page load, so a session-only limit is bypassed by rotating it. A
looser per-IP bucket (400 tokens, 40/s) sits behind it as the backstop rotation
can't shed, sized well above the session limit so an office behind one NAT isn't
throttled. Both are checked and debited all-or-nothing in a single script call;
a partial debit would charge a caller for a request that was refused. The IP is
read off the socket rather than `X-Forwarded-For`, since keying on a header the
client can set would reintroduce the bypass.

The script returns the pre-debit budget of the tightest bucket, which is what
makes `Retry-After` a real number. Before that it returned nothing, so Python
computed `tokens_requested / refill_rate` — a constant. Every rejection claimed
the same 0.1 s wait no matter how far over budget the caller was.

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

**Grounding is enforced in the prompt, not hoped for.** Retrieved passages are
numbered and the model is told to answer only from them, to cite the numbers it
used, and to say it doesn't know when the context falls short. The earlier
prompt — "use the provided context to answer questions accurately" — permitted
the model to answer a retrieval miss from training data, which is the failure
mode this whole document is about: the system looks confident and is unmoored.

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

**And it is measured.** `python -m eval.run_eval` scores a 12-question golden set
against the real pipeline: recall@1 0.917, recall@3 1.000, MRR 0.958, context
precision 1.000. Running it with `--chunker fixed` is the more interesting half —
it revised ADR-006's own claim downward, showing that rank barely differs between
the two chunkers and that structural chunking's advantage is signal strength (a
40% higher score on the correct chunk, a 37% wider margin over the runner-up)
rather than the difference between working and broken. An eval whose only
function is to confirm what you already believed isn't an eval.

**Traces are pruned at startup** past `TRACE_RETENTION_HOURS` (30 days), since
the metrics endpoint never queries beyond 7 days and an append-only table with no
answer to "and then what?" is a strange thing to find in a project about
observability.

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

**Where it sits:** before retrieval, not after. This is the whole point of a
cache — it must skip the work it exists to avoid — and the first version had it
backwards, consulting the cache only after a vector search had already run. The
answer's chunks are cached alongside it, so a hit still populates the retrieval
panel without a search. The query is embedded once and the same vector feeds
both the semantic lookup and, on a miss, the vector store.

**Without it:** every paraphrase of a popular question is a fresh LLM call. At a
40% hit rate, the cache is deleting 40% of the platform's marginal cost. A hit
returns in tens of milliseconds against ~1.5 s for a generated answer; the
remaining cost is one embedding, which is unavoidable because the semantic tier
needs the vector to compare. (The exact tier is a hash lookup and could skip
even that — see the note at the end of this document.)

### Model router with fallback (`services/router.py`)

**Why:** not every query deserves Opus. The router maps queries to tiers — `fast`
(claude-haiku-4-5), `quality` (claude-sonnet-5), `deep` (claude-opus-5) — by
user hint, then by `LLM_DEFAULT_TIER`, promoted one step for long queries. The
configured default matters: the heuristic used to be `fast if words < 50 else
quality`, and since almost every real question is under fifty words that made
routing a constant function with `deep` unreachable. When a tier fails, it walks the remaining
tiers in order and sets `fallback_triggered` on the trace, so degradation is
*surfaced*, never silent: the Generate node pulses in the UI and the receipt names
the model that actually answered.

**Without it:** either everything runs on the most expensive model (10–60x cost
for short factual queries), or a single model outage takes the whole product down.

**The provider is a setting, not an assumption.** `LLM_PROVIDER=openai` points
the same tier/fallback/breaker machinery at any OpenAI-compatible endpoint —
Groq, Google AI Studio, OpenRouter, a local Ollama. This exists for a blunt
reason: there is no free Anthropic API tier, and a portfolio project a stranger
cannot run is a portfolio project nobody runs. Tier names stay; only the model
ids behind them move, via `LLM_MODEL_FAST` / `_QUALITY` / `_DEEP`.

One consequence worth stating rather than hiding: `cost_for` prices only the
Claude models, and returns **zero** for anything else. An unknown model used to
inherit Sonnet's rate as a fallback, which put an invented dollar figure on the
receipt for a free-tier call. A receipt reading $0.0000 is true; a receipt that
guesses is worse than one that abstains.

### LLM service with circuit breaker (`services/llm.py`)

**Why:** each tier has its own circuit breaker — 3 consecutive failures open it,
and it stays open for a 30-second cooldown. While open, calls to that tier fail
instantly, which does two things: the router falls back immediately instead of
waiting out a timeout, and the struggling upstream gets breathing room instead of
a retry storm.

**Not every failure is a tier failure.** A breaker protects a *struggling
upstream*; a 401, 400 or 404 means the upstream is perfectly healthy and the
request was wrong. Those are classified as permanent (`is_retryable`), and they
neither trip the breaker nor walk the fallback chain. This was a real bug found
by pointing the app at an invalid key: the router dutifully tried Haiku, Sonnet
and Opus, all of which returned the same 401, and after three requests every
breaker was open — so the error the operator saw became "Circuit breaker open
for tier deep" instead of "your API key is invalid". Three round trips spent to
replace a precise message with a misleading one.

**Without it:** during a provider incident, every request eats a full timeout
before failing over, latency explodes, and my own retries make the provider's
incident worse.

### Observability (`services/observability.py`)

**Why:** this is the product. Every request gets a `RequestTrace` — per-stage
milliseconds, cache status, model used, fallback flag, tokens, cost, retrieved
chunk IDs — persisted to SQLite. The metrics endpoint aggregates them into
p50/p95/p99 latency, cache hit rate, error rate, cost, and model breakdown.

**Every stage the UI draws is a stage the backend timed.** `embed_ms`,
`cache_ms`, `retrieval_ms` and `llm_ms` are measured independently and ride out
on the SSE events as they happen, so the pipeline trace can lay out its four
segments live from real numbers. This was worth fixing precisely because it was
the one place the project wasn't keeping its own promise: `embed_ms` was
measured and then discarded, and the frontend split the Embed/Retrieve segment
at a hardcoded 35/65 ratio. A visualisation that invents its own numbers is
worse than no visualisation, because it is believed.

**Rates are measured over the traffic, not the window.** `req_per_sec` divided
by the window length until recently, so the 30-second load test the README asks
you to run reported 0.06 req/s inside a 1h window — the flagship demo of the Ops
dashboard made a burst look like an idle system. It is now computed over the
span between the first and last request in the window, and `observed_span_sec`
ships alongside it so the figure can be read in context.

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
| Primary model down | Streaming error → circuit breaker (opens after 3 *transient* failures, 30 s cooldown) | Router walks remaining tiers (`quality` → `fast` → `deep` order preserved) | `fallback_triggered: true` in trace; Generate node pulses; receipt names the substitute model |
| Bad API key / malformed request | 401, 400, 404 → classified permanent | No fallback, no breaker trip — fails on the first tier | SSE `error` event carrying the provider's own message |
| All model tiers down | Every tier raises | Request fails with an explicit error event | SSE `error` event with the message; error rate on Ops dashboard |
| Unreadable or oversized upload | `UnsupportedDocument`, or the streamed read exceeding `MAX_UPLOAD_BYTES` | Rejected before any embedding runs; no Document row is written | `400` or `413`; the rail shows no debris entry |
| Rate limit exceeded | Session or IP bucket empty | Request rejected before any work is done | `429` + `Retry-After`, computed from the budget left in the tightest bucket |
| Embedding failure | Exception in `embed_query` | No vector, so both the semantic cache and the vector search are skipped; the query goes to the LLM with zero context | Cache stage shows miss, empty chunk panel |

## The next thing I'd change

A cache hit currently costs one embedding, because the pipeline embeds before
consulting either tier and the semantic tier needs the vector. But the *exact*
tier doesn't — it's a SHA-256 lookup. Splitting the check in two (hash lookup →
embed only on miss → semantic lookup) would make a repeat question a sub-
millisecond answer instead of a tens-of-milliseconds one.

The reason it isn't done: it turns a clean four-stage pipeline into a five-stage
one with the cache appearing twice, and the visualisation is the product here.
It's a real optimisation with a real presentation cost, which makes it a
decision rather than a bug.

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
