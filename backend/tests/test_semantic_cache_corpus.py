"""The cache demo in README.md step 4, run against the real embedding model.

This exists because the README promised a `hit_semantic` for a pair that
measures 0.755 — below the 0.80 threshold — so the demo it tells you to perform
in an interview missed. ADR-002 was right all along ("paraphrases between 0.67
and 0.80 are misses we accept"); the README contradicted it.

Any change to SEMANTIC_CACHE_THRESHOLD, to the embedding model, or to the
documented script has to keep these passing or the docs are lying again.
"""

import pytest

from app.services.cache import CacheLayer

# The exact strings README.md step 4 tells the reader to type. Measured:
#   paraphrase 0.942, negation 0.982, distinct topic 0.256, unrelated 0.134.
# The negation scoring *above* the paraphrase is the demo: no threshold can
# separate them, which is why polarity is checked lexically.
BASE_QUERY = "How much water does life support recycle?"
PARAPHRASE = "What percentage of water does life support recycle?"
NEGATED = "How much water does life support not recycle?"

# Controls for the bands ADR-002 documents.
DISTINCT_TOPIC = "How much power do the solar arrays generate?"
UNRELATED = "What is the capital of France?"

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def embed():
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    model = ONNXMiniLM_L6_V2()

    def _embed(text: str) -> list[float]:
        return [float(v) for v in model([text])[0]]

    return _embed


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))


class TestDocumentedSimilarityBands:
    def test_the_documented_paraphrase_clears_the_threshold(self, embed, config):
        score = cosine(embed(BASE_QUERY), embed(PARAPHRASE))
        assert score >= config.SEMANTIC_CACHE_THRESHOLD, (
            f"README step 4 promises a semantic hit, but this pair scores {score:.3f}"
        )

    def test_the_negated_form_also_clears_the_threshold(self, embed, config):
        """The whole point of the polarity guard: a threshold cannot catch this."""
        score = cosine(embed(BASE_QUERY), embed(NEGATED))
        assert score >= config.SEMANTIC_CACHE_THRESHOLD, (
            f"negation scores {score:.3f}; if it were below the threshold the "
            "lexical guard would be redundant and the demo would prove nothing"
        )

    def test_a_distinct_topic_stays_well_below_the_threshold(self, embed, config):
        score = cosine(embed(BASE_QUERY), embed(DISTINCT_TOPIC))
        assert score < 0.5

    def test_an_unrelated_question_scores_near_zero(self, embed):
        assert cosine(embed(BASE_QUERY), embed(UNRELATED)) < 0.2


class TestCacheServesTheDemo:
    """End to end through CacheLayer, which is what the demo actually exercises."""

    async def test_a_paraphrase_is_served_from_cache(self, embed, config):
        cache = CacheLayer(config, redis_client=None)
        await cache.set(BASE_QUERY, embed(BASE_QUERY), "93 percent.", [{"chunk_id": "c1"}])

        result = await cache.get(PARAPHRASE, embed(PARAPHRASE))
        assert result["hit"] is True
        assert result["tier"] == "semantic"
        assert result["response"] == "93 percent."

    async def test_the_negated_form_misses_despite_a_high_score(self, embed, config):
        cache = CacheLayer(config, redis_client=None)
        await cache.set(BASE_QUERY, embed(BASE_QUERY), "93 percent.", [])

        result = await cache.get(NEGATED, embed(NEGATED))
        assert result["hit"] is False, (
            "the polarity guard must refuse an affirmative answer to a negated "
            "question however close the vectors are"
        )
