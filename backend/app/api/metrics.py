import logging
from fastapi import APIRouter
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
    if _observability is None:
        return {"error": "observability not ready"}
    return _observability.get_metrics(window)
