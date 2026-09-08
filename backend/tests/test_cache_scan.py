"""Semantic cache lookup at scale.

The scan was a pure-Python loop computing cosine one float at a time over a
384-dimensional vector per entry — roughly 200k multiply-adds on a full store,
on the request path, in a project whose whole subject is latency. numpy is
already installed (chromadb depends on it), so the loop was costing something
for nothing.

Behaviour must not change: same hit, same tier, same similarity, same polarity
guard. These pin that, and that the vectorised path agrees with the scalar one.
"""

import math

import pytest

from app.services.cache import CacheLayer, _cosine


def unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


class TestCosineAgreement:
    def test_identical_vectors_score_one(self):
        v = unit(0.3, 0.9, 0.1, 0.4)
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self):
        assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_a_zero_vector_scores_zero_rather_than_dividing_by_zero(self):
        assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_matches_a_hand_computed_value(self):
        # cos between (1,0) and (1,1) is 1/sqrt(2).
        assert _cosine([1.0, 0.0], [1.0, 1.0]) == pytest.approx(1 / math.sqrt(2))


class TestLookupAtScale:
    async def test_finds_the_best_match_in_a_full_store(self, config):
        """512 entries is the store's cap, which is the size that has to be fast."""
        cache = CacheLayer(config, redis_client=None)
        target = unit(1.0, 0.02, 0.0, 0.0)

        for i in range(400):
            # Deliberately unrelated directions.
            await cache.set(f"filler {i}", unit(0.0, 0.0, 1.0, float(i % 7) + 1), f"r{i}", [])
        await cache.set("the one", target, "correct answer", [{"chunk_id": "c9"}])
        for i in range(100):
            await cache.set(f"tail {i}", unit(0.0, 1.0, 0.0, float(i % 5) + 1), f"t{i}", [])

        result = await cache.get("a paraphrase", unit(1.0, 0.05, 0.0, 0.0))
        assert result["hit"] is True
        assert result["response"] == "correct answer"
        assert result["similarity"] > config.SEMANTIC_CACHE_THRESHOLD
        assert result["chunks"] == [{"chunk_id": "c9"}]

    async def test_returns_a_miss_when_nothing_clears_the_threshold(self, config):
        cache = CacheLayer(config, redis_client=None)
        for i in range(50):
            await cache.set(f"q{i}", unit(0.0, 1.0, 0.0, float(i + 1)), f"r{i}", [])
        result = await cache.get("unrelated", unit(1.0, 0.0, 0.0, 0.0))
        assert result["hit"] is False
        assert result["similarity"] is None

    async def test_the_polarity_guard_survives_vectorisation(self, config):
        """The negated form scores above threshold; only polarity may reject it."""
        cache = CacheLayer(config, redis_client=None)
        v = unit(1.0, 0.1, 0.0, 0.0)
        await cache.set("is the linker able to emit debug info", v, "yes", [])

        near_identical = unit(1.0, 0.11, 0.0, 0.0)
        assert _cosine(v, near_identical) > config.SEMANTIC_CACHE_THRESHOLD

        result = await cache.get("is the linker not able to emit debug info", near_identical)
        assert result["hit"] is False, "a negated query must not be served the affirmative"

    async def test_expired_entries_are_skipped(self, config):
        # A negative TTL rather than 0: with TTL=0 the entry's expiry lands in
        # the same clock tick as the lookup (Windows' timer is ~15 ms), so
        # `expires_at < now` is false and the test measures timer resolution
        # instead of expiry.
        cache = CacheLayer(config.model_copy(update={"CACHE_TTL": -1}), redis_client=None)
        v = unit(1.0, 0.0, 0.0, 0.0)
        await cache.set("old", v, "stale", [])
        assert (await cache.get("new", v))["hit"] is False

    async def test_an_empty_store_is_a_miss_not_a_crash(self, config):
        cache = CacheLayer(config, redis_client=None)
        assert (await cache.get("anything", unit(1.0, 0.0)))["hit"] is False
