import hashlib
import logging
import uuid
from datetime import datetime

from sqlmodel import Session, select

from ..models import Chunk, Document

logger = logging.getLogger(__name__)


def _extract_text(file_bytes: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    elif name.endswith(".docx"):
        import io
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        return file_bytes.decode("utf-8", errors="replace")


class IngestService:
    def __init__(self, chunker, embedding_service, vector_store):
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.vector_store = vector_store

    async def ingest_document(self, file_bytes: bytes, filename: str, db: Session) -> Document:
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        existing = db.exec(select(Document).where(Document.content_hash == content_hash)).first()
        if existing:
            return existing

        doc = Document(
            filename=filename,
            content_hash=content_hash,
            status="processing",
            uploaded_at=datetime.utcnow(),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        try:
            text = _extract_text(file_bytes, filename)
            raw_chunks = self.chunker.chunk(text, {})
            texts = [c["text"] for c in raw_chunks]
            embeddings = await self.embedding_service.embed_batch(texts)

            chunk_records = []
            chunk_dicts = []
            for c, emb in zip(raw_chunks, embeddings):
                cid = str(uuid.uuid4())
                chunk_records.append(Chunk(
                    id=cid,
                    document_id=doc.id,
                    text=c["text"],
                    chunk_index=c["chunk_index"],
                    page_number=c.get("page_number"),
                ))
                chunk_dicts.append({
                    "id": cid,
                    "document_id": doc.id,
                    "text": c["text"],
                    "chunk_index": c["chunk_index"],
                    "page_number": c.get("page_number"),
                })

            self.vector_store.upsert(chunk_dicts, embeddings)
            for cr in chunk_records:
                db.add(cr)

            doc.chunk_count = len(chunk_records)
            doc.status = "ready"
            db.add(doc)
            db.commit()
            db.refresh(doc)
        except Exception as e:
            logger.error(f"Ingestion failed for {filename}: {e}")
            doc.status = "error"
            db.add(doc)
            db.commit()
            raise

        return doc
