# ADR-002: A semantic cache tier, not exact-match alone

**Status:** Accepted
**Date:** 2026-07

## Context

Every cache miss in Glasshouse is an LLM call: real money, and ~1.5 s of latency
that dominates the entire pipeline. So the cache hit rate is the single number
with the most leverage over both cost and p95.

An exact-match cache keyed on the normalized query is the obvious first move, and
it is cheap and safe. But natural-language queries have an enormous surface area
for the same intent. "Summarize the key findings", "What are the key findings?",
and "what were the main findings" are three distinct keys and one question. An
exact-match cache treats them as three misses and pays three times.

## Decision

Run **two tiers, exact first, then semantic.**

- **Exact tier** — SHA-256 of the lowercased, whitespace-collapsed query, stored
  in Redis with a 1-hour TTL (in-memory LRU of 256 entries when Redis is down).
- **Semantic tier** — cosine similarity against cached query embeddings; a hit
  requires **≥ 0.80** (configurable) *and* matching lexical polarity. Bounded at
  512 entries.

The ordering is not arbitrary. Exact matching is O(1), requires no embedding, and
**cannot** return a wrong answer, so it runs first and the semantic tier only
sees what exact matching missed. The query embedding the semantic tier needs is
already computed for retrieval, so the marginal cost of the second tier is a
similarity scan, not a model call.

The tier that answered is **surfaced in the UI** — the cache badge reads
"semantic, 0.97" rather than just "hit". A cache that silently returns someone
else's answer is a correctness bug you cannot see; making the tier and the
similarity visible turns it into an observable one.

## Consequences

**What this buys.** Paraphrases of popular questions collapse onto one LLM call.
At a 40% hit rate the cache removes 40% of marginal cost and turns ~1.5 s answers
into ~10 ms answers — and cache hits contribute essentially zero concurrency,
which is what makes the capacity numbers in ARCHITECTURE.md work.

**The threshold was measured, and the intuitive value was wrong.** This tier
originally shipped at 0.95 — the number that *sounds* like "definitely the same
question". Instrumenting it against real queries showed 0.95 essentially never
fires: the tier was dead code that had never served a single hit. Measuring the
actual bands on this corpus with `all-MiniLM-L6-v2`:

| Query relationship | Observed cosine | Should hit? |
| --- | --- | --- |
| Same intent, reworded | 0.67 – 0.99 | yes |
| **Negation of a cached query** | **0.825 – 0.982** | **no** |
| Related but distinct topic | 0.26 – 0.40 | no |
| Unrelated | < 0.15 | no |

The bands overlap, and that overlap is the entire finding. Taking the demo pair
in README step 4 against the base question "How much water does life support
recycle?":

| Variant | Cosine | Verdict |
| --- | --- | --- |
| "What **percentage** of water does life support recycle?" | 0.942 | hit |
| "How much water does life support **not** recycle?" | **0.982** | miss (polarity) |
| "How much power do the solar arrays generate?" | 0.256 | miss |
| "What is the capital of France?" | 0.134 | miss |

The negation scores **higher than the genuine paraphrase**. Any threshold that
admits the one admits the other. These four numbers are asserted in
`backend/tests/test_semantic_cache_corpus.py`, because an earlier version of this
README documented a "paraphrase" that actually scored 0.626 and therefore missed
— the doc claimed a hit the code could never produce.

Two things fall out of that table. First, same-intent paraphrases bottom out
around 0.67, so any threshold above ~0.9 rejects most genuine repeats — the
setting now sits at **0.80**, which is twice the top of the related-but-distinct
band and still catches natural rewordings. That is a deliberate precision-over-
recall choice: the gap from 0.40 to 0.80 is the safety margin, and the paraphrases
between 0.67 and 0.80 are misses we accept in exchange for it.

Second, and more importantly: **negation is not separable by cosine at any
threshold.** "Is the linker able to emit split debug info?" against "is the linker
*not* able to…" scores 0.825 — above two thirds of the paraphrase band — and the
water-recovery pair above reaches 0.982, higher than any paraphrase of it. There
is no value that admits real paraphrases and excludes that. The reason is structural,
not a tuning failure: negation is a one-token lexical change carrying a total
semantic inversion, and a bi-encoder trained for topical similarity barely
registers it.

So polarity is checked **lexically**, not left to the vector: a small negator word
list, and a cached entry is skipped outright when its polarity differs from the
query's, however close the embeddings are. This is the right shape of fix — the
embedding decides *topic*, cheap explicit code decides *polarity* — and it
decouples the threshold from the inversion risk, which is what let 0.95 drop to
0.80 safely. Verified behaviour: two paraphrases hit at 0.958 and 0.903 in
~450–580 ms at zero cost, while the negated form and a related-but-distinct
question both correctly miss.

**Where this is still weak.** The negator list is English, hand-written, and
word-level, so it does not catch antonym pairs ("did it grow" vs "did it shrink")
or morphological negation — "unable" happens to be listed, "non-reproducible" is
not. It catches the common case, not the general one.

A load test made a second gap concrete. Firing 160 requests with the queries
`burst probe 0`, `burst probe 1`, … produced a **64% semantic cache hit rate**:
strings differing only by a numeral embed almost identically, so the cache served
one answer for all of them. Polarity is not the only semantics a bi-encoder
flattens — **numbers, dates, names, and units** are the same failure in a
different costume, and "what was revenue in 2023?" versus "…in 2024?" is the
version of this that matters in production. The lexical guard does not help,
because nothing is negated.

That has a cheap partial fix of the same shape — require any digit-or-entity
tokens to match before allowing a semantic hit — and the same complete fix as
negation: a cross-encoder re-check on candidates. It is called out here rather
than quietly patched because it is the honest summary of what this tier is: a
topical similarity match, useful and measurably cheap, with a known class of
false positives that a threshold cannot close.

A more complete answer is a
cross-encoder re-check on candidate hits above the threshold — accurate, and cheap
because it runs on a handful of candidates rather than the corpus. That is the
documented upgrade path; the lexical guard is what earns the hit rate today.

**Bounding.** Both tiers are bounded — TTL expiry plus LRU on exact, a 512-entry
cap on semantic — so stale answers age out and neither store grows without limit.

**The cache does not help at all on a cold burst.** This one was measured too, and
it is the most interesting limitation here because it is structural rather than a
tuning problem. Firing 103 *identical* queries concurrently at a cold cache
produced a hit rate of **0.0089** — two hits, not the ~102 the tier exists to
deliver. Every request checked the cache before any of them had finished writing
to it, so all 103 missed, all 103 called the model, and all 103 then wrote the
same entry. This is the classic **cache stampede** (thundering herd): the cache
only absorbs load *after* one request has paid for the answer, and under
concurrency there is a window where no one has.

It matters exactly where caching is supposed to matter most — a traffic spike on
one popular question is the stampede's ideal shape, and it is also the moment the
cost saving is most needed. Note that the numbers reported earlier in this
document are honest despite this: they come from sequential requests, which is
how a cache is normally exercised and how the demo drives it.

The fix is **single-flight coalescing**: on a miss, the first request registers an
in-flight marker keyed by the query hash, and later arrivals await that future
instead of starting their own generation. N concurrent identical queries then cost
one model call. The complications are real and are why it is documented rather
than shipped late in this project — the marker must be released on failure or
every subsequent caller hangs, it needs a timeout shorter than the request
timeout, and doing it across processes means a Redis lock with all the liveness
questions that implies. Streaming makes it harder still: a joined waiter cannot
replay tokens it wasn't there for, so it either waits for the full answer and
loses streaming, or the leader must fan its token stream out to the waiters.

Worth saying plainly in an interview: the observable symptom was a cache hit rate
near zero on a run where it should have been near one, and that number was only
visible because the platform reports it. A system without this dashboard would
have had the same bug and shown nothing.

## Alternatives considered

- **Exact match only** — safe and simple, and it never returns a wrong answer.
  Rejected because it misses the majority of real repeat traffic, which arrives
  as paraphrase rather than as byte-identical strings.
- **Semantic only** — drops a tier of code, but pays an embedding comparison for
  queries that a hash lookup would have answered in O(1), and gives up the
  guarantee that identical queries are always answered identically.
- **Caching on the retrieved chunk set instead of the query** — genuinely
  appealing, because two differently-worded queries that retrieve the same chunks
  are strong evidence of the same intent. Rejected for now because it caches
  *after* the expensive-ish retrieval step rather than before, so it saves the
  LLM call but not the embedding and vector search. Worth revisiting as a third
  tier.
