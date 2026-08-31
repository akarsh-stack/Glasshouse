import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.cache import CacheLayer
from ..services.observability import ObservabilityService
from ..services.rate_limiter import TokenBucketRateLimiter
from ..services.retrieval import RetrievalOrchestrator
from ..services.router import ModelRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_retrieval: Optional[RetrievalOrchestrator] = None
_cache: Optional[CacheLayer] = None
_llm_router: Optional[ModelRouter] = None
_rate_limiter: Optional[TokenBucketRateLimiter] = None
_observability: Optional[ObservabilityService] = None


def set_services(retrieval, cache, llm_router, rate_limiter, observability):
    global _retrieval, _cache, _llm_router, _rate_limiter, _observability
    _retrieval = retrieval
    _cache = cache
    _llm_router = llm_router
    _rate_limiter = rate_limiter
    _observability = observability


class QueryRequest(BaseModel):
    query: str
    tier_hint: Optional[str] = None
    session_id: Optional[str] = None


async def _enforce_rate_limit(req: QueryRequest, client_ip: Optional[str] = None) -> None:
    """Reject over-budget requests with a real 429 before streaming starts.

    This deliberately runs *outside* the SSE generator. Once a StreamingResponse
    begins, the status line is already on the wire and cannot be changed — a
    rejection reported from inside the generator would be an HTTP 200 carrying an
    error payload. Every intermediary that keys off status (proxies, load
    balancers, client retry logic, `curl --fail`) would read that as success, and
    a limiter that only the frontend can see is not a limiter.

    The trace is created and finished here too, so a rejection is still a logged
    request. It is recorded as `rate_limited` rather than `error`: a 429 is the
    system working as designed, and folding it into error_rate would make a
    healthy platform under load look broken.
    """
    if not _rate_limiter:
        return

    result = await _rate_limiter.check_and_consume(
        req.session_id or "anonymous", client_ip=client_ip
    )
    if result["allowed"]:
        return

    if _observability:
        trace = _observability.start_trace(str(uuid.uuid4()))
        trace.query_text = req.query
        trace.rate_limited = True
        _observability.finish_trace(trace)

    retry_after = result["retry_after"]
    raise HTTPException(
        status_code=429,
        detail={
            "message": "Rate limit exceeded",
            # Duplicated in the body because Retry-After is integer seconds by
            # spec, which rounds a 0.4s wait up to 1s. The UI counts down from
            # the precise value; proxies get the standards-compliant header.
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(max(1, int(-(-retry_after // 1))))},
    )


async def _stream(req: QueryRequest):
    request_id = str(uuid.uuid4())

    def sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    trace = _observability.start_trace(request_id) if _observability else None
    if trace:
        trace.query_text = req.query

    # 1. Embed. Exactly once per request: the same vector is what the cache is
    #    keyed on semantically *and* what the vector store is searched with, so
    #    computing it twice was paying the batch window twice for one answer.
    query_embedding: list[float] = []
    embed_ms = 0.0
    if _retrieval:
        try:
            query_embedding, embed_ms = await _retrieval.embed_query(req.query)
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
    embed_ms = round(embed_ms, 2)
    if trace:
        _observability.record_stage(trace, "embed_ms", embed_ms)

    # 2. Cache, *before* retrieval. A cache exists to skip downstream work; the
    #    previous order retrieved first and then discovered the answer was
    #    already known, so a "free" hit still paid for a vector search.
    t_cache = time.monotonic()
    cache_result = {"hit": False, "tier": None, "response": None, "chunks": [], "similarity": None}
    if _cache and query_embedding:
        try:
            cache_result = await _cache.get(req.query, query_embedding)
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
    cache_ms = round((time.monotonic() - t_cache) * 1000, 2)

    cache_status = "miss"
    if cache_result["hit"]:
        cache_status = f"hit_{cache_result['tier']}"

    if trace:
        trace.cache_status = cache_status
        _observability.record_stage(trace, "cache_ms", cache_ms)

    yield sse({
        "type": "cache",
        "status": cache_status,
        "similarity": cache_result["similarity"],
        "embed_ms": embed_ms,
        "cache_ms": cache_ms,
    })

    if cache_result["hit"]:
        # The chunks were cached with the answer, so the retrieval panel still
        # fills — at zero cost, which is the point.
        cached_chunks = cache_result.get("chunks") or []
        if trace:
            trace.retrieved_chunks = cached_chunks
        yield sse({
            "type": "retrieval",
            "chunks": cached_chunks,
            "retrieve_ms": 0.0,
            "from_cache": True,
        })
        yield sse({"type": "chunk", "text": cache_result["response"]})
        if trace:
            _observability.finish_trace(trace)
        # Same trace shape as the miss path so the UI never has to branch. A cache
        # hit spends no tokens and calls no model, hence the zeros and empty model.
        yield sse({
            "type": "done",
            "trace": {
                "request_id": request_id,
                "cache_status": cache_status,
                "model_used": "",
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "fallback_triggered": False,
                "stages_ms": trace.stages_ms if trace else {},
            },
        })
        return

    # 3. Retrieval, reusing the embedding from step 1.
    chunks: list[dict] = []
    retrieve_ms = 0.0
    if _retrieval and query_embedding:
        try:
            chunks, retrieve_ms = await _retrieval.search(query_embedding)
        except Exception as e:
            logger.warning(f"Retrieval failed: {e}")
    retrieve_ms = round(retrieve_ms, 2)
    if trace:
        _observability.record_stage(trace, "retrieval_ms", retrieve_ms)
        trace.retrieved_chunks = chunks

    yield sse({
        "type": "retrieval",
        "chunks": chunks,
        "retrieve_ms": retrieve_ms,
        "from_cache": False,
    })

    # 4. LLM generation
    tier = _llm_router.route(req.query, req.tier_hint) if _llm_router else "quality"
    full_response = []
    tokens_in = tokens_out = 0
    cost_usd = 0.0
    model_used = ""

    t1 = time.monotonic()
    try:
        async for event in _llm_router.generate_with_fallback(req.query, tier, chunks, trace):
            if event["type"] == "chunk":
                full_response.append(event["text"])
                yield sse(event)
            elif event["type"] == "done":
                tokens_in = event.get("tokens_in", 0)
                tokens_out = event.get("tokens_out", 0)
                cost_usd = event.get("cost_usd", 0.0)
                model_used = event.get("model", "")
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        # A failed request is still a request. Persist it before returning or the
        # Ops dashboard's error rate is structurally incapable of being non-zero.
        if trace:
            _observability.record_stage(trace, "llm_ms", (time.monotonic() - t1) * 1000)
            trace.error = True
            trace.error_message = str(e)
            _observability.finish_trace(trace)
        yield sse({"type": "error", "message": str(e), "request_id": request_id})
        return

    if trace:
        _observability.record_stage(trace, "llm_ms", (time.monotonic() - t1) * 1000)
        trace.tokens_in = tokens_in
        trace.tokens_out = tokens_out
        trace.cost_usd = cost_usd
        trace.model_used = model_used

    # cache store — chunks included, so a future hit can skip retrieval too
    if _cache and query_embedding and full_response:
        try:
            await _cache.set(req.query, query_embedding, "".join(full_response), chunks)
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

    if trace:
        _observability.finish_trace(trace)

    trace_data = {}
    if trace:
        trace_data = {
            "request_id": request_id,
            "cache_status": cache_status,
            "model_used": model_used,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "fallback_triggered": trace.fallback_triggered if trace else False,
            "stages_ms": trace.stages_ms if trace else {},
        }

    yield sse({"type": "done", "trace": trace_data})


@router.post("/api/query")
async def query_endpoint(req: QueryRequest, request: Request):
    # Must precede the StreamingResponse: see _enforce_rate_limit's docstring.
    # The IP comes off the socket rather than X-Forwarded-For, which a client
    # can set freely — see TokenBucketRateLimiter's docstring.
    await _enforce_rate_limit(req, request.client.host if request.client else None)
    return StreamingResponse(
        _stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
