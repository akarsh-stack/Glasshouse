# ADR-001: Embedded ChromaDB behind a `VectorStore` Protocol

**Status:** Accepted
**Date:** 2026-07

## Context

Glasshouse needs a vector store for chunk retrieval. The realistic options were
embedded ChromaDB, Qdrant (server), pgvector on Postgres, and a managed service
like Pinecone. Two constraints pull in opposite directions:

1. A stranger should be able to `git clone` and have a working system in under
   five minutes. Every external service in the startup path is a step where that
   fails — a container that won't pull, a port already bound, a connection string
   to fill in.
2. The store is the component most likely to be replaced. It is the piece that
   hits a scaling wall first, and it is the piece an interviewer is most likely
   to ask "what if you outgrow it?" about.

## Decision

Use **embedded ChromaDB** (cosine space, persisted to disk) as the shipping
implementation, and have every caller depend on a three-method `VectorStore`
Protocol — `upsert`, `query`, `delete_by_document` — rather than on Chroma.

The Protocol is structural, not an ABC: an adapter satisfies it by having the
right method signatures, with no import of Glasshouse types and no inheritance.

## Consequences

**What this buys.** Zero external infrastructure in the default path — no
container, no connection string, no separate process. Chroma persists to a
directory, so state survives a restart, which matters for a demo where you
ingest a PDF and then talk about it. And because the dependency is on the
Protocol, swapping engines is a new adapter class (~70 lines) plus a config
change, not a refactor that touches retrieval, ingestion, and the API layer.

**What it costs.** Embedded Chroma is single-node and single-process. It has no
replication, no quantization, and its metadata filtering is weaker than
Qdrant's. Realistically it is fine to roughly a million vectors on one node; past
that the scaling path in ARCHITECTURE.md applies (replicate, then shard by
`document_id` or tenant, then swap the engine).

**Keeping the abstraction honest.** An interface that has only ever had one
implementation is a claim, not a fact — it almost always turns out to have leaked
something from the concrete type. `docker-compose.yml` carries a **Qdrant service
behind a profile** so the second implementation is cheap to actually write and
run, which is the only way to know the seam holds.

## Alternatives considered

- **Qdrant from day one** — better engine, genuinely multi-node. Rejected because
  it puts a required container in the clone-and-run path to buy headroom this
  project does not need yet. It stays in compose behind a profile.
- **pgvector** — attractive if the project already had Postgres, since it
  collapses two datastores into one and gives transactional consistency between
  chunk rows and vectors. Glasshouse uses SQLite, so pgvector would mean adding
  Postgres purely for the vector index.
- **Pinecone or another managed service** — requires an API key before the app
  runs at all, which breaks the five-minute clone-and-run goal, and adds a
  network hop to a latency the project exists to measure.
