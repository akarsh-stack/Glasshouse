import time
import logging

logger = logging.getLogger(__name__)


class RetrievalOrchestrator:
    def __init__(self, embedding_service, vector_store, config):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.config = config

    async def embed_query(self, query_text: str) -> tuple[list[float], float]:
        """Embed once, and report how long it took.

        Split out from `search` because the caller needs the vector *before* it
        knows whether retrieval will happen at all: the cache is consulted with
        this embedding, and a hit means no vector search. Returning the timing
        here rather than measuring around the call is what lets the trace carry
        a real `embed_ms` instead of folding it into retrieval.
        """
        t0 = time.monotonic()
        embedding = await self.embedding_service.embed_one(query_text)
        return embedding, (time.monotonic() - t0) * 1000

    async def search(
        self,
        embedding: list[float],
        top_k: int | None = None,
        score_threshold: float | None = None,
        token_budget: int | None = None,
    ) -> tuple[list[dict], float]:
        """Vector search plus gating, for an embedding the caller already has."""
        top_k = top_k or self.config.TOP_K
        score_threshold = score_threshold if score_threshold is not None else self.config.SCORE_THRESHOLD
        token_budget = token_budget or self.config.TOKEN_BUDGET

        t0 = time.monotonic()

        # Ask the store for top_k unfiltered, then gate *relative to the best
        # hit*. Absolute cosine cutoffs don't survive contact with real data:
        # question->passage similarity with MiniLM lands around 0.2-0.5 even for
        # a correct match, so an absolute 0.3 silently drops right answers, while
        # 0.15 lets everything through. What actually separates signal from noise
        # is the gap between the top hit and the rest.
        chunks = self.vector_store.query(embedding, top_k, None)
        chunks.sort(key=lambda c: c["score"], reverse=True)

        if chunks:
            top = chunks[0]["score"]
            floor = max(score_threshold, top * self.config.RELATIVE_SCORE_RATIO)
            kept = [c for c in chunks if c["score"] >= floor]
            # Never return nothing when the store had something: a weak-but-best
            # chunk plus a visible low score beats a silent no-context answer.
            chunks = kept or chunks[:1]

        selected = []
        used_tokens = 0
        for chunk in chunks:
            tokens = len(chunk["text"].split())
            if used_tokens + tokens > token_budget:
                break
            selected.append(chunk)
            used_tokens += tokens

        return selected, (time.monotonic() - t0) * 1000

    async def retrieve(self, query_text: str, **kwargs) -> dict:
        """Embed then search. Kept for callers that have no cache to consult."""
        embedding, embed_ms = await self.embed_query(query_text)
        chunks, retrieve_ms = await self.search(embedding, **kwargs)
        return {"chunks": chunks, "embed_ms": embed_ms, "retrieve_ms": retrieve_ms}
