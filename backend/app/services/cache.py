import hashlib
import json
import logging
import time
from typing import Optional

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
            return {"hit": True, "tier": "exact", "response": value["response"], "similarity": 1.0}

        # semantic match
        now = time.time()
        best_sim = 0.0
        best_resp = None
        polarity = _polarity(query_text)
        for entry in self._semantic_store:
            if entry["expires_at"] < now:
                continue
            # Refuse to serve an affirmative answer to a negated question, or vice
            # versa, however close the vectors are.
            if entry["polarity"] != polarity:
                continue
            sim = _cosine(query_embedding, entry["embedding"])
            if sim > best_sim:
                best_sim = sim
                best_resp = entry["response"]

        if best_sim >= self.config.SEMANTIC_CACHE_THRESHOLD and best_resp is not None:
            return {"hit": True, "tier": "semantic", "response": best_resp, "similarity": best_sim}

        return {"hit": False, "tier": None, "response": None, "similarity": None}

    async def set(self, query_text: str, query_embedding: list[float], response_text: str) -> None:
        key = self._exact_key(query_text)
        payload = json.dumps({"response": response_text})
        ttl = self.config.CACHE_TTL

        if self.redis:
            try:
                await self.redis.setex(key, ttl, payload)
            except Exception:
                self._lru[key] = {"response": response_text}
        else:
            self._lru[key] = {"response": response_text}

        expires_at = time.time() + ttl
        self._semantic_store.append({
            "key": key,
            "embedding": query_embedding,
            "response": response_text,
            "expires_at": expires_at,
            "polarity": _polarity(query_text),
        })
        # keep store bounded
        if len(self._semantic_store) > 512:
            self._semantic_store = self._semantic_store[-512:]
