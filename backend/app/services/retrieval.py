import time
import logging

logger = logging.getLogger(__name__)


class RetrievalOrchestrator:
    def __init__(self, embedding_service, vector_store, config):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.config = config

    async def retrieve(
        self,
        query_text: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
        token_budget: int | None = None,
    ) -> dict:
        top_k = top_k or self.config.TOP_K
        score_threshold = score_threshold if score_threshold is not None else self.config.SCORE_THRESHOLD
        token_budget = token_budget or self.config.TOKEN_BUDGET

        t0 = time.monotonic()
        embedding = await self.embedding_service.embed_one(query_text)
        embed_ms = (time.monotonic() - t0) * 1000

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

        return {"chunks": selected, "embed_ms": embed_ms}
