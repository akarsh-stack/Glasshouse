import logging
from fastapi import APIRouter, HTTPException
from ..services.observability import ObservabilityService
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter()

_observability: Optional[ObservabilityService] = None


def set_observability(svc: ObservabilityService):
    global _observability
    _observability = svc


@router.get("/api/traces/{request_id}")
def get_trace(request_id: str):
    if _observability is None:
        raise HTTPException(status_code=503, detail="Observability not ready")
    trace = _observability.get_trace(request_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
