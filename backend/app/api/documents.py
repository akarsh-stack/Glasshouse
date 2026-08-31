import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlmodel import Session, select

from ..config import config
from ..models import Chunk, Document, get_session
from ..services.ingestion import IngestService, UnsupportedDocument

logger = logging.getLogger(__name__)
router = APIRouter()

_ingest_service: Optional[IngestService] = None
_rate_limiter = None


def set_ingest_service(svc: IngestService, rate_limiter=None):
    global _ingest_service, _rate_limiter
    _ingest_service = svc
    _rate_limiter = rate_limiter


def get_ingest_service() -> IngestService:
    if _ingest_service is None:
        raise HTTPException(status_code=503, detail="Ingestion service not ready")
    return _ingest_service


async def _read_within_limit(file: UploadFile) -> bytes:
    """Read the upload, refusing anything over the cap.

    Streamed in chunks rather than `await file.read()`, because reading first
    and checking the length afterwards means a 2 GB upload is already resident
    before it gets rejected. `content-length` alone isn't enough — it's client
    supplied and absent on chunked transfers.
    """
    limit = config.MAX_UPLOAD_BYTES
    buf = bytearray()
    while chunk := await file.read(64 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {limit} byte upload limit",
            )
    return bytes(buf)


@router.post("/api/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    svc: IngestService = Depends(get_ingest_service),
):
    # Ingestion chunks, embeds and indexes arbitrary input — the most expensive
    # thing an unauthenticated caller can trigger. It belongs behind the same
    # limiter as /api/query, at a higher token cost.
    if _rate_limiter is not None:
        result = await _rate_limiter.check_and_consume(
            f"upload:{request.client.host if request.client else 'anonymous'}",
            tokens=config.UPLOAD_TOKEN_COST,
            client_ip=request.client.host if request.client else None,
        )
        if not result["allowed"]:
            raise HTTPException(
                status_code=429,
                detail={"message": "Upload rate limit exceeded", "retry_after": result["retry_after"]},
                headers={"Retry-After": str(max(1, int(-(-result["retry_after"] // 1))))},
            )

    file_bytes = await _read_within_limit(file)
    try:
        return await svc.ingest_document(file_bytes, file.filename or "upload", db)
    except UnsupportedDocument as e:
        # A file we can't parse is the caller's problem; surfacing it as a 500
        # sends the reader looking for a server bug that isn't there.
        raise HTTPException(status_code=400, detail=str(e)) from e


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
