# ADR-006: Structural chunking and relative score gating

**Status:** Accepted
**Date:** 2026-07

## Context

Glasshouse's first retrieval implementation was the textbook one: split documents
into fixed 220-word windows with 40 words of overlap, embed each, and keep any
result scoring above an absolute cosine threshold of 0.3.

It returned **zero chunks for a question the corpus plainly answered.** Not a
wrong answer — no context at all, so the system degraded to a no-context LLM
reply about a document it was holding. Two independent defects were stacked on
top of each other, and each one alone was enough to cause it.

### Defect 1: the absolute threshold was above the real score range

The intuition behind "0.3 is a low bar" is that cosine runs to 1.0, so 0.3 must
be permissive. That intuition is wrong for question→passage retrieval. Measured
on this corpus with `all-MiniLM-L6-v2`, a **correct** match scores **0.19–0.61**.
A question and the passage answering it are not paraphrases of each other — they
are different registers ("how much water is recycled?" vs. "the assembly
electrolyses water at 2.3 kilograms per hour") — and a bi-encoder scores that
pairing far lower than it scores two similar sentences.

So 0.3 sat *inside* the correct-match range and silently deleted true positives.
The debris-avoidance query's best chunk scored **0.240** and was discarded. Any
fixed number here is fragile: 0.3 drops right answers, 0.15 admits everything,
and both values shift with the embedding model, the corpus, and the phrasing.

### Defect 2: fixed-width chunks are topic grab-bags

Fixed windows cut wherever the word counter runs out, which routinely lands a
chunk across a section boundary. The sample document produced 3 chunks spanning
6 topics. Chunk 1 covered orbital altitude, power, *and* attitude control — and
it won a **water recovery** query at 0.447, beating the chunk that actually
discussed water.

That is the failure mode worth understanding: a multi-topic chunk's embedding is
the average of its topics, so it points at none of them. It matches many queries
weakly and no query strongly — a mediocre answer to everything, which in a
top-k ranking is exactly how you outrank the specific correct chunk.

## Decision

**Split on structure first, size second** (`chunkers/structural.py`), and **gate
retrieval relative to the top hit** rather than against a fixed floor.

**Chunking.** Never merge across a heading; split paragraphs at blank lines; pack
consecutive paragraphs only up to `max_words`. A section longer than the cap
falls back to overlapping windows *within* that section, so oversized input
degrades to the old behaviour instead of failing. The governing heading is
**prepended to every chunk it covers**: "Life support — the oxygen generation
assembly…" is far more retrievable than the bare sentence, and it hands the model
the section name for free.

PDFs need more than markdown does. `pypdf` returns a page as hard-wrapped lines
with no blank lines and no markup, so a `#`-only rule collapses a well-structured
PDF back into one grab-bag chunk. Unmarked headings are detected from three
signals together: few words, no sentence-ending punctuation, and **substantially
shorter than the median line in that document**. The relative-length test is what
makes it work on wrapped prose — body lines run to the full column width while a
heading stops early — and it self-calibrates per document rather than hard-coding
a column width.

**Retrieval gating.** Ask the store for `top_k` unfiltered, then keep chunks
scoring within `RELATIVE_SCORE_RATIO` (0.55) of the best hit, with a near-zero
absolute floor (0.08) retained only to reject genuine noise. The signal that
separates a real match from a bad one is not the absolute score — it is **the gap
between the top hit and the rest**. A top hit at 0.60 with runners-up at 0.55 is
a document with several relevant sections; a top hit at 0.22 with runners-up at
0.08 is one weak match and noise. The ratio reads both correctly, and it is
invariant to the corpus and model shifts that break a fixed threshold.

When everything is filtered out, the top chunk is returned anyway rather than
nothing. A weak-but-best chunk with a visibly low score beats a silent
no-context answer: the user can see the system was unsure, which is the whole
premise of the product.

## Measured, after the fact — and it revises the claim above

This ADR was originally written from a single dramatic failure. There is now a
12-question golden set over the sample corpus (`backend/eval/golden_set.json`)
and a harness that runs the real chunker, real ONNX embeddings and a real Chroma
collection: `python -m eval.run_eval [--chunker fixed]`.

| Metric | structural | fixed 220-word |
|---|---|---|
| recall@1 | 0.917 | 0.917 |
| recall@3 | 1.000 | 1.000 |
| MRR | 0.958 | 0.944 |
| context precision (survives gating) | **1.000** | 0.917 |
| mean score of the correct chunk | **0.507** | 0.363 |
| mean margin over the best wrong chunk | **0.204** | 0.149 |
| chunks indexed | 9 | 4 |

**Two of these numbers are identical, and that matters.** Rank is essentially the
same either way — fixed-width chunking still puts the right passage first 11
times out of 12. The claim at the top of this document, that fixed chunking
"returned zero chunks for a question the corpus plainly answered", does not
reproduce today, and `--before` (fixed chunks plus the original absolute 0.3
floor) doesn't reproduce it either. The reason is that the *other* half of this
decision — relative gating, plus the "return the top chunk rather than nothing"
guard — rescues fixed chunking almost completely. The two fixes overlap, and
the gating one was doing most of the work.

**Where structural genuinely wins is signal strength, not rank.** The correct
chunk scores 40% higher (0.507 vs 0.363) and beats the best wrong chunk by a 37%
wider margin (0.204 vs 0.149). That is exactly the grab-bag mechanism this ADR
describes — a chunk averaging four topics points at none of them — and it is the
property that decays as a corpus grows. On nine chunks a 0.15 margin is enough;
on ninety thousand it is not. The one case where it already bites is
`debris-screening`, where fixed chunking retrieves the right passage at rank 3
and then *gates it out of the prompt entirely* — the model never sees it. That
is the 0.917 context precision above, and it is the failure mode that matters,
because a passage retrieved but not delivered is a passage that may as well not
exist.

So: structural chunking stays, on evidence, but the honest summary is "a
consistently stronger signal and one fewer dropped passage", not "the difference
between working and broken". The dramatic framing earlier in this document
reflects a one-off observation that the eval does not support.

## Consequences

**Measured effect.** On the query that returned nothing, retrieval now returns
the correct chunk at **0.605** — previously 0.240 on the *wrong* chunk. The
sample markdown yields 6 single-topic chunks instead of 3 grab-bags; the sample
PDF yields 3 instead of 1. A PDF-only question scores 0.689 on the right chunk
while the unrelated document's chunks are excluded entirely by the gate.

**What it costs.** Chunk sizes are now uneven, because documents are. A one-line
section becomes a one-line chunk, which is why runt chunks below `min_words` are
folded into a neighbour. Heading detection is a heuristic with false positives: a
short unpunctuated sentence can be read as a heading. That error is deliberately
the cheap one — a spurious heading only adds a prefix and a split boundary, while
a missed heading fuses two topics into an embedding that points at neither.

**What it does not fix.** Relative gating cannot tell "several relevant sections"
from "several equally irrelevant ones" — if the whole corpus is off-topic, the
top hit and its neighbours are uniformly bad and the ratio happily keeps them.
The absolute floor is the only backstop, and it is deliberately near zero. The
real answer is a re-ranking cross-encoder over the candidate set, which scores
query–passage pairs jointly instead of comparing two independently-computed
vectors, and is the natural next upgrade alongside hybrid BM25 + RRF.

## Alternatives considered

- **Tune the absolute threshold instead.** Rejected: this is what was already
  being done, and the measured 0.19–0.61 spread for correct matches shows there
  is no value that separates signal from noise across queries. It also has to be
  re-tuned for every corpus and embedding model.
- **Semantic chunking** (embed sentences, cut where adjacent similarity drops).
  Genuinely better on documents with no markup at all, and model-agnostic. Not
  chosen because it costs an embedding pass per sentence at ingest and adds a
  second threshold to defend, while headings already encode the author's own
  topic boundaries — free, exact structure that a similarity heuristic is trying
  to reconstruct.
- **Return top-k unconditionally, no gate.** Simple and never drops a right
  answer. Rejected because it pads the prompt with irrelevant chunks on every
  narrow query, which costs tokens and measurably invites the model to use them.
- **One chunk per document.** Works only until a document exceeds the context
  window, and destroys citation precision — the UI cites a chunk, and "the whole
  document" is not a citation.
