"""The query pipeline's ordering and its per-stage timings.

Two properties are under test here, and they were both broken:

  * A cache hit must short-circuit *before* retrieval, and the query must be
    embedded exactly once. The pipeline used to retrieve first and embed twice,
    so a "free" cache hit still paid for a vector search and two model calls.

  * Every stage the UI draws must be backed by a measured number. The trace
    used to carry only `retrieval_ms` and `llm_ms`, so the frontend invented the
    embed/retrieve split from a hardcoded ratio.
"""

import json

import pytest
from conftest import FakeEmbeddingService, FakeModelRouter, FakeVectorStore

from app.api import query as query_api
from app.services.cache import CacheLayer
from app.services.retrieval import RetrievalOrchestrator


@pytest.fixture
def pipeline(config, observability):
    """Wire the real query module up to fakes and hand back the parts."""
    embedding = FakeEmbeddingService()
    store = FakeVectorStore()
    retrieval = RetrievalOrchestrator(embedding, store, config)
    cache = CacheLayer(config, redis_client=None)
    llm = FakeModelRouter()
    query_api.set_services(retrieval, cache, llm, None, observability)
    return {
        "embedding": embedding,
        "store": store,
        "cache": cache,
        "llm": llm,
        "observability": observability,
    }


async def run_query(text: str, session_id: str = "s1") -> list[dict]:
    req = query_api.QueryRequest(query=text, session_id=session_id)
    events = []
    async for frame in query_api._stream(req):
        assert frame.startswith("data: ")
        events.append(json.loads(frame[6:]))
    return events


def event_of(events: list[dict], kind: str) -> dict:
    matches = [e for e in events if e["type"] == kind]
    assert matches, f"no {kind!r} event in {[e['type'] for e in events]}"
    return matches[0]


class TestSingleEmbedding:
    async def test_a_query_is_embedded_exactly_once(self, pipeline):
        await run_query("How much water is recycled?")
        assert pipeline["embedding"].embed_calls == ["How much water is recycled?"]


class TestCacheShortCircuit:
    async def test_cache_hit_skips_the_vector_store(self, pipeline):
        await run_query("How much water is recycled?")
        calls_after_miss = pipeline["store"].query_calls
        assert calls_after_miss == 1, "the first (missing) query must retrieve"

        await run_query("How much water is recycled?")
        assert pipeline["store"].query_calls == calls_after_miss, (
            "a cache hit must not touch the vector store"
        )

    async def test_cache_hit_skips_the_llm(self, pipeline):
        await run_query("How much water is recycled?")
        await run_query("How much water is recycled?")
        assert pipeline["llm"].calls == 1

    async def test_cache_hit_still_reports_the_chunks_that_produced_it(self, pipeline):
        await run_query("How much water is recycled?")
        events = await run_query("How much water is recycled?")

        assert event_of(events, "cache")["status"] == "hit_exact"
        retrieval = event_of(events, "retrieval")
        assert retrieval["from_cache"] is True
        assert [c["chunk_id"] for c in retrieval["chunks"]] == ["c1"], (
            "cached answers must carry the chunks they were grounded in, so the "
            "UI keeps its retrieval panel without paying for a search"
        )

    async def test_cache_verdict_is_emitted_before_retrieval(self, pipeline):
        events = await run_query("How much water is recycled?")
        kinds = [e["type"] for e in events]
        assert kinds.index("cache") < kinds.index("retrieval"), (
            "the cache decides whether retrieval happens, so its event comes first"
        )


class TestMeasuredStages:
    async def test_every_stage_the_ui_draws_is_measured(self, pipeline):
        events = await run_query("How much water is recycled?")
        stages = event_of(events, "done")["trace"]["stages_ms"]
        assert set(stages) == {"embed_ms", "cache_ms", "retrieval_ms", "llm_ms"}

    async def test_cache_event_carries_its_own_timings(self, pipeline):
        cache_event = event_of(await run_query("q"), "cache")
        assert isinstance(cache_event["embed_ms"], float)
        assert isinstance(cache_event["cache_ms"], float)

    async def test_retrieval_event_carries_its_own_timing(self, pipeline):
        retrieval = event_of(await run_query("q"), "retrieval")
        assert isinstance(retrieval["retrieve_ms"], float)

    async def test_retrieval_timing_excludes_the_embedding(self, pipeline):
        """`retrieval_ms` used to include embed time, double-counting it."""
        events = await run_query("q")
        stages = event_of(events, "done")["trace"]["stages_ms"]
        retrieve_ms = event_of(events, "retrieval")["retrieve_ms"]
        assert stages["retrieval_ms"] == pytest.approx(retrieve_ms, abs=1e-6)

    async def test_a_cache_hit_records_no_retrieval_or_llm_time(self, pipeline):
        await run_query("How much water is recycled?")
        events = await run_query("How much water is recycled?")
        stages = event_of(events, "done")["trace"]["stages_ms"]
        assert set(stages) == {"embed_ms", "cache_ms"}
