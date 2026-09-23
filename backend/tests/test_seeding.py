"""Seeding the sample corpus on an empty store.

A fresh deploy has no documents, so a visitor lands on an app with nothing to
ask about and no starter questions (those are derived from what's loaded). On a
host without a persistent disk that happens after every restart, which makes the
deployed demo useless on arrival.

Seeding is opt-in via `SEED_SAMPLES` so local development doesn't silently
re-ingest on every boot, and it is skipped when documents already exist so it
can never duplicate or clobber a real corpus.
"""

import pytest
from conftest import FakeEmbeddingService, FakeVectorStore
from sqlmodel import Session, SQLModel, create_engine, select

from app.chunkers.structural import StructuralChunker
from app.models import Document
from app.services.ingestion import IngestService
from app.services.seeding import seed_samples


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'seed.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def service():
    return IngestService(StructuralChunker(220, 40), FakeEmbeddingService(), FakeVectorStore())


def count(engine) -> int:
    with Session(engine) as db:
        return len(db.exec(select(Document)).all())


class TestSeeding:
    async def test_ingests_the_sample_corpus_into_an_empty_store(self, service, engine):
        added = await seed_samples(service, engine)
        assert added == 2, "both sample documents should land"
        assert count(engine) == 2

    async def test_is_a_no_op_when_documents_already_exist(self, service, engine):
        await seed_samples(service, engine)
        before = count(engine)
        added = await seed_samples(service, engine)
        assert added == 0, "seeding must never run over an existing corpus"
        assert count(engine) == before

    async def test_seeded_documents_are_queryable(self, service, engine):
        """Chunked and embedded, not just rows in a table."""
        await seed_samples(service, engine)
        with Session(engine) as db:
            docs = db.exec(select(Document)).all()
        assert all(d.status == "ready" for d in docs)
        assert all(d.chunk_count > 0 for d in docs)

    async def test_a_missing_samples_directory_is_survivable(self, service, engine, monkeypatch):
        # A slimmed-down image might not ship samples/. That should log and
        # continue, not prevent the app from starting.
        import app.services.seeding as seeding

        monkeypatch.setattr(seeding, "SAMPLES_DIR", tmp_missing := seeding.SAMPLES_DIR / "nope")
        assert not tmp_missing.exists()
        assert await seed_samples(service, engine) == 0

    async def test_one_bad_file_does_not_abort_the_rest(self, service, engine, monkeypatch, tmp_path):
        import app.services.seeding as seeding

        # Its own directory: `tmp_path` also holds the test's seed.db, and a
        # stray database counted as a seeded document the first time round.
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "notes.md").write_text(
            "# Heading\n\nBody text long enough to survive chunking here.\n"
        )
        (corpus / "broken.pdf").write_bytes(b"not a pdf")
        monkeypatch.setattr(seeding, "SAMPLES_DIR", corpus)

        assert await seed_samples(service, engine) == 1

    async def test_non_documents_are_not_seeded(self, service, engine, monkeypatch, tmp_path):
        """Unknown extensions decode as UTF-8 text, so a database would
        otherwise become a document full of mojibake competing in retrieval."""
        import app.services.seeding as seeding

        corpus = tmp_path / "mixed"
        corpus.mkdir()
        (corpus / "notes.md").write_text("# Heading\n\nEnough body text to chunk cleanly.\n")
        (corpus / "state.db").write_bytes(b"SQLite format 3\x00binary junk")
        (corpus / ".DS_Store").write_bytes(b"\x00\x01")
        monkeypatch.setattr(seeding, "SAMPLES_DIR", corpus)

        assert await seed_samples(service, engine) == 1
