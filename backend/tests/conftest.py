"""Shared fakes for the pipeline tests.

Everything here is a real object except the two things a test can't afford to
call for real: the embedding model and the Anthropic API. Both fakes count
their invocations, because several of these tests are specifically about *how
many times* the pipeline does expensive work.
"""

import sys
from pathlib import Path

import pytest
from sqlmodel import SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Config  # noqa: E402
from app.services.observability import ObservabilityService  # noqa: E402


class FakeEmbeddingService:
    """Deterministic 4-dim embeddings, keyed by query text.

    `embed_calls` is the assertion surface for "the query is embedded once per
    request" — the pipeline used to embed it twice.
    """

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self.vectors = vectors or {}
        self.embed_calls: list[str] = []

    async def embed_one(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self.vectors.get(text, [1.0, 0.0, 0.0, 0.0])

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_one(t) for t in texts]


class FakeVectorStore:
    """Records every query so a test can assert retrieval was skipped."""

    def __init__(self, chunks: list[dict] | None = None):
        self.chunks = chunks if chunks is not None else [
            {
                "chunk_id": "c1",
                "score": 0.61,
                "text": "Water recovery runs at 93 percent.",
                "document_id": "d1",
                "chunk_index": 0,
                "page_number": None,
            }
        ]
        self.query_calls = 0

    def upsert(self, chunks, embeddings) -> None:  # pragma: no cover - unused
        pass

    def query(self, embedding, top_k, score_threshold=None) -> list[dict]:
        self.query_calls += 1
        return [dict(c) for c in self.chunks]

    def delete_by_document(self, document_id: str) -> None:  # pragma: no cover
        pass


class FakeModelRouter:
    """Emits a fixed two-event stream in place of a real LLM call."""

    def __init__(self, text: str = "Ninety-three percent."):
        self.text = text
        self.calls = 0

    def route(self, query_text, tier_hint=None) -> str:
        return tier_hint or "fast"

    async def generate_with_fallback(self, prompt, tier, context_chunks, trace):
        self.calls += 1
        yield {"type": "chunk", "text": self.text}
        yield {
            "type": "done",
            "tokens_in": 10,
            "tokens_out": 5,
            "cost_usd": 0.0001,
            "model": "claude-haiku-4-5",
        }


@pytest.fixture
def config() -> Config:
    """Defaults only.

    `_env_file=None` is load-bearing: without it the suite reads the developer's
    own `.env`, so whoever has `LLM_MODEL_FAST` set locally sees different
    results from CI. Tests assert on documented defaults, not on this machine.
    """
    return Config(_env_file=None, ANTHROPIC_API_KEY="test-key")


@pytest.fixture
def observability() -> ObservabilityService:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return ObservabilityService(engine)
