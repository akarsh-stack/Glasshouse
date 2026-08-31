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


@router.get("/api/metrics")
def get_metrics(window: str = "1h"):
    # 503, not a 200 carrying an {"error": ...} body — the frontend types this
    # response as MetricsData and would otherwise render a payload with every
    # figure missing as though the window were simply empty.
    if _observability is None:
        raise HTTPException(status_code=503, detail="Observability not ready")
    return _observability.get_metrics(window)
