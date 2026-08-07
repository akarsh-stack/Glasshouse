import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select

from ..models import Chunk, Document, get_session
from ..services.ingestion import IngestService

logger = logging.getLogger(__name__)
router = APIRouter()

_ingest_service: Optional[IngestService] = None


def set_ingest_service(svc: IngestService):
    global _ingest_service
    _ingest_service = svc


def get_ingest_service() -> IngestService:
    if _ingest_service is None:
        raise HTTPException(status_code=503, detail="Ingestion service not ready")
    return _ingest_service


@router.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    svc: IngestService = Depends(get_ingest_service),
):
    file_bytes = await file.read()
    doc = await svc.ingest_document(file_bytes, file.filename or "upload", db)
    return doc


@router.get("/api/documents")
def list_documents(db: Session = Depends(get_session)):
    return db.exec(select(Document)).all()


@router.delete("/api/documents/{doc_id}")
def delete_document(
    doc_id: str,
    db: Session = Depends(get_session),
    svc: IngestService = Depends(get_ingest_service),
):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        svc.vector_store.delete_by_document(doc_id)
    except Exception as e:
        logger.warning(f"Vector store delete failed: {e}")
    chunks = db.exec(select(Chunk).where(Chunk.document_id == doc_id)).all()
    for chunk in chunks:
        db.delete(chunk)
    db.delete(doc)
    db.commit()
    return {"deleted": doc_id}
