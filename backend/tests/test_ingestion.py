"""Document ingestion.

`page_number` was plumbed the whole way — SQLModel column, Chroma metadata, API
response, `types.ts`, and a `p.{n}` badge in ChunkCards.tsx — but ingestion
passed `{}` as the chunker metadata, so it was `None` for every chunk ever
written. The badge could not render. These tests make the field carry data.
"""

import io

import pytest
from conftest import FakeEmbeddingService, FakeVectorStore
from sqlmodel import Session, SQLModel, create_engine, select

from app.chunkers.structural import StructuralChunker
from app.models import Chunk
from app.services.ingestion import IngestService, UnsupportedDocument


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def service():
    return IngestService(StructuralChunker(220, 40), FakeEmbeddingService(), FakeVectorStore())


def make_pdf(pages: list[list[str]]) -> bytes:
    """A real multi-page PDF, built the same hand-rolled way as the sample fixture.

    No new dependency: this reuses the byte-level writer from
    `make_sample_pdf.py`, so pypdf's genuine extraction path is what gets tested
    rather than a doctored file.
    """
    n = len(pages)
    # 1 catalog, 2 pages tree, then per page: page object + content stream,
    # and finally the shared font.
    font_obj = 3 + n * 2
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(n))

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
    ]
    for i, lines in enumerate(pages):
        content = "BT /F1 11 Tf 54 742 Td 15 TL\n"
        for line in lines:
            safe = line.replace("\\", "").replace("(", "").replace(")", "")
            content += f"({safe}) Tj T*\n"
        content += "ET"
        stream = content.encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
            f"/Contents {4 + i * 2} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref).encode() + b"\n%%EOF\n"
    )
    return out


class TestPageNumbers:
    async def test_pdf_chunks_carry_the_page_they_came_from(self, service, db):
        pdf = make_pdf([
            ["Station vitals",
             "The station orbits at 412 kilometres altitude nominally and holds",
             "an inclination of 51.6 degrees across eleven pressurised modules."],
            ["Life support",
             "Water recovery reaches 93 percent of onboard water every day via",
             "humidity capture and urine processing through the reclaim loop."],
        ])
        doc = await service.ingest_document(pdf, "notes.pdf", db)

        chunks = db.exec(select(Chunk).where(Chunk.document_id == doc.id)).all()
        pages = {c.page_number for c in chunks}
        assert pages == {1, 2}, f"expected one chunk per page, got pages {pages}"

    async def test_page_numbers_are_one_based(self, service, db):
        pdf = make_pdf([["Station vitals",
                         "Only page here with enough words to survive chunking intact",
                         "and to clear the minimum chunk size the chunker enforces."]])
        doc = await service.ingest_document(pdf, "one.pdf", db)
        chunks = db.exec(select(Chunk).where(Chunk.document_id == doc.id)).all()
        assert [c.page_number for c in chunks] == [1]

    async def test_chunk_index_stays_unique_across_pages(self, service, db):
        """Chunkers restart their index per call, so pages must not collide."""
        pdf = make_pdf([
            [f"Section {i}",
             f"Body text for section {i} that is long enough to be kept whole",
             "and not folded into a neighbouring chunk by the runt rule."]
            for i in range(4)
        ])
        doc = await service.ingest_document(pdf, "many.pdf", db)
        chunks = db.exec(select(Chunk).where(Chunk.document_id == doc.id)).all()
        indices = [c.chunk_index for c in chunks]
        assert len(set(indices)) == len(indices), f"duplicate chunk_index: {indices}"

    async def test_markdown_has_no_page_numbers(self, service, db):
        doc = await service.ingest_document(
            b"# Heading\n\nSome body text that is long enough to survive chunking.\n",
            "notes.md",
            db,
        )
        chunks = db.exec(select(Chunk).where(Chunk.document_id == doc.id)).all()
        assert all(c.page_number is None for c in chunks)


class TestUnsupportedInput:
    async def test_an_unreadable_pdf_is_a_client_error(self, service, db):
        """A bad upload is the caller's fault, not a 500."""
        with pytest.raises(UnsupportedDocument):
            await service.ingest_document(b"this is not a pdf", "broken.pdf", db)

    async def test_an_empty_file_is_rejected(self, service, db):
        with pytest.raises(UnsupportedDocument):
            await service.ingest_document(b"", "empty.md", db)

    async def test_a_failed_ingest_does_not_leave_a_processing_row(self, service, db):
        from app.models import Document

        with pytest.raises(UnsupportedDocument):
            await service.ingest_document(b"", "empty.md", db)
        assert db.exec(select(Document)).all() == []
