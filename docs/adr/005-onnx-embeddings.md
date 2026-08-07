# ADR-005: ONNX runtime as the default embedding backend

**Status:** Accepted
**Date:** 2026-07

## Context

Glasshouse embeds locally by default — no API key needed to run the retrieval
half of the pipeline, which matters because a stranger should be able to clone
and get a working system in under five minutes.

The obvious way to do that is `sentence-transformers`, which is the canonical
library for `all-MiniLM-L6-v2`. But `pip install sentence-transformers` pulls
**PyTorch**: roughly 2.5 GB installed, a multi-minute download on a normal
connection, and a stack of native DLLs. For a project whose install story is a
stated requirement, that dependency is most of the install.

It is also brittle in ways that have nothing to do with this project. On the
machine this was built on, Windows Application Control refused to load
`torch/lib/shm.dll` outright — a machine policy, not a bug, and not something the
app can work around. A dependency that can be blocked by local policy is a
dependency that can stop a demo cold.

## Decision

Default `EMBEDDING_PROVIDER=onnx`, which runs **the same `all-MiniLM-L6-v2`
model** through `chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2` — a
quantized ONNX export executed by `onnxruntime`. 384-dimensional output,
identical to the PyTorch path.

`sentence-transformers` stays available as an explicit provider, moved out of
`requirements.txt` into `requirements-torch.txt`. `openai` remains the third
provider for hosted embeddings.

## Consequences

**What this buys.** `chromadb` is already a dependency and it already carries
onnxruntime, so the default embedding backend costs **zero new packages** — the
model itself is an ~80 MB download on first use, cached under
`~/.cache/chroma`. Install goes from ~2.5 GB to ~80 MB, and the clone-and-run
target stops depending on a PyTorch install succeeding. No native DLL surface
that local policy is likely to object to.

**What it costs.** Three real limitations, in order of how likely they are to
matter:

1. **The model is pinned.** The ONNX path is one specific exported model.
   `EMBEDDING_MODEL` has no effect on it — swapping to `bge-small` or
   `all-mpnet-base-v2` means switching to the `sentence-transformers` provider.
2. **CPU only.** onnxruntime here has no GPU execution provider configured. At
   the throughput this project targets that is irrelevant — micro-batching
   already collapses concurrent requests into one invocation, and embedding is
   ~10–30 ms against a ~1.5 s LLM call — but it is a real ceiling for bulk
   ingestion of a large corpus.
3. **Quantization changes the numbers slightly.** The quantized export is not
   bit-identical to the PyTorch model, so cosine similarities differ in the third
   or fourth decimal place. This matters wherever a similarity is compared
   against a constant: the semantic cache threshold of 0.80 and the retrieval
   score ratio ([ADR-002](002-semantic-cache-tier.md),
   [ADR-006](006-chunking-and-relative-score-gating.md)) were both measured
   against *this* backend, so switching providers means re-measuring them. That
   fragility is part of why retrieval gates on the ratio to the top hit rather
   than an absolute cutoff. **Vectors from the two backends are not
   interchangeable** — switching providers invalidates the existing Chroma
   collection and it must be re-ingested.

**Why this is a config flag and not a hard-coded choice.** The point of
[ADR-001](001-chromadb-behind-a-protocol.md) applies here too: the fast default
should not foreclose the flexible option. Local ONNX for the demo, PyTorch when
you want a different model or a GPU, OpenAI when you want someone else to own
the throughput.

## Alternatives considered

- **`sentence-transformers` as the default** — the conventional choice, and the
  right one if the project needed model flexibility or GPU throughput out of the
  box. Rejected because it makes PyTorch a hard requirement for a path where the
  ONNX export produces the same vectors.
- **OpenAI embeddings as the default** — better embedding quality, no local
  compute, and `text-embedding-3-small` is cheap. Rejected because it requires a
  second API key before anything works at all, and it puts a network round trip
  inside a latency this project exists to measure.
- **Ship the ONNX file in the repo** — removes the 80 MB first-run download.
  Rejected: an 80 MB binary in git for a one-time cached fetch is a bad trade.
