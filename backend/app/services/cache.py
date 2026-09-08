import hashlib
import json
import logging
import time
from typing import Optional

import numpy as np
from cachetools import LRUCache

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


# Measured on this corpus with all-MiniLM-L6-v2: same-intent paraphrases score
# 0.83-0.91, but "is X NOT true?" against "is X true?" scores 0.825 — inside the
# paraphrase band. No cosine threshold can separate them, because negation is a
# small lexical change with a total semantic inversion, and bi-encoders barely
# register it. So polarity is checked lexically rather than trusted to the vector.
_NEGATORS = frozenset({
    "not", "no", "never", "none", "cannot", "cant", "can't", "isnt", "isn't",
    "arent", "aren't", "doesnt", "doesn't", "dont", "don't", "didnt", "didn't",
    "wasnt", "wasn't", "werent", "weren't", "wont", "won't", "without",
    "neither", "nor", "unable", "fails", "fail",
})


def _polarity(text: str) -> bool:
    """True if the query appears to contain a negation."""
    words = {w.strip(".,!?;:\"'()") for w in _normalize(text).split()}
    return bool(words & _NEGATORS)


class CacheLayer:
    def __init__(self, config, redis_client=None):
        self.config = config
        self.redis = redis_client
        self._lru: LRUCache = LRUCache(maxsize=256)
        self._semantic_store: list[dict] = []  # {key, embedding, response, expires_at}
        # Row-aligned with _semantic_store, rebuilt lazily. Converting 512x384
        # Python floats to numpy on every lookup cost more than the dot product
        # it fed; building once per write and reusing it is ~50x cheaper.
        self._matrix: Optional[np.ndarray] = None

    def _embedding_matrix(self) -> np.ndarray:
        if self._matrix is None:
            self._matrix = np.asarray(
                [e["embedding"] for e in self._semantic_store], dtype=np.float32
            )
        return self._matrix

    def _exact_key(self, text: str) -> str:
        return "gh:exact:" + hashlib.sha256(_normalize(text).encode()).hexdigest()

    async def get(self, query_text: str, query_embedding: list[float]) -> dict:
        key = self._exact_key(query_text)

        # exact match
        value = None
        if self.redis:
            try:
                value = await self.redis.get(key)
                if value:
                    value = json.loads(value)
            except Exception:
                value = self._lru.get(key)
        else:
            value = self._lru.get(key)

        if value:
            return {
                "hit": True,
                "tier": "exact",
                "response": value["response"],
                # Entries written before chunks were cached have no "chunks" key.
                "chunks": value.get("chunks", []),
                "similarity": 1.0,
            }

        # Semantic match, vectorised.
        #
        # This was a Python loop calling _cosine per entry — on a full store
        # that is 512 x 384 multiply-adds one float at a time, on the request
        # path, in a project about latency. numpy is already a dependency
        # (chromadb pulls it), so the loop was costing something for nothing.
        #
        # Candidates are filtered *before* the dot product rather than after:
        # an expired or opposite-polarity entry should never be measured
        # against, and skipping them shrinks the matrix as well.
        now = time.time()
        polarity = _polarity(query_text)
        rows: list[int] = []
        candidates: list[dict] = []
        for i, entry in enumerate(self._semantic_store):
            if entry["expires_at"] >= now and entry["polarity"] == polarity:
                rows.append(i)
                candidates.append(entry)

        if not candidates:
            return {"hit": False, "tier": None, "response": None, "chunks": [], "similarity": None}

        matrix = self._embedding_matrix()[rows]
        query = np.asarray(query_embedding, dtype=np.float32)

        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
        # A zero-norm row would divide by zero; those entries score 0, matching
        # what the scalar implementation returned for a degenerate vector.
        with np.errstate(divide="ignore", invalid="ignore"):
            sims = np.where(norms > 0, matrix @ query / norms, 0.0)

        best_index = int(np.argmax(sims))
        best_sim = float(sims[best_index])
        best_entry = candidates[best_index] if best_sim > 0 else None

        if best_sim >= self.config.SEMANTIC_CACHE_THRESHOLD and best_entry is not None:
            return {
                "hit": True,
                "tier": "semantic",
                "response": best_entry["response"],
                "chunks": best_entry["chunks"],
                "similarity": best_sim,
            }

        return {"hit": False, "tier": None, "response": None, "chunks": [], "similarity": None}

    async def set(
        self,
        query_text: str,
        query_embedding: list[float],
        response_text: str,
        chunks: list[dict] | None = None,
    ) -> None:
        """Cache the answer *and* the chunks that grounded it.

        Storing the chunks is what lets a cache hit skip retrieval outright: the
        UI still gets its retrieval panel, but no embedding is compared and no
        vector search runs. Without them a "free" hit would still have to pay
        for a search just to populate the display.
        """
        key = self._exact_key(query_text)
        chunks = chunks or []
        payload = json.dumps({"response": response_text, "chunks": chunks})
        ttl = self.config.CACHE_TTL

        if self.redis:
            try:
                await self.redis.setex(key, ttl, payload)
            except Exception:
                self._lru[key] = {"response": response_text, "chunks": chunks}
        else:
            self._lru[key] = {"response": response_text, "chunks": chunks}

        expires_at = time.time() + ttl
        self._semantic_store.append({
            "key": key,
            "embedding": query_embedding,
            "response": response_text,
            "chunks": chunks,
            "expires_at": expires_at,
            "polarity": _polarity(query_text),
        })
        # keep store bounded
        if len(self._semantic_store) > 512:
            self._semantic_store = self._semantic_store[-512:]

        # Both paths above changed the store, so the cached matrix no longer
        # lines up with it. Invalidate rather than patch: an append is one row
        # but the truncation reindexes everything, and a stale matrix would
        # silently return the wrong entry's answer.
        self._matrix = None
