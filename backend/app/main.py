import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import config
from . import models
from .models import init_db
from .chunkers.fixed import FixedSizeChunker
from .chunkers.structural import StructuralChunker
from .services.embedding import EmbeddingService
from .services.vector_store import ChromaVectorStore
from .services.ingestion import IngestService
from .services.retrieval import RetrievalOrchestrator
from .services.cache import CacheLayer
from .services.llm import LLMService, resolve_models
from .services.router import ModelRouter
from .services.rate_limiter import TokenBucketRateLimiter
from .services.observability import ObservabilityService
from .services.seeding import seed_samples
from .api import documents, query, metrics, traces

logger = logging.getLogger(__name__)

embedding_service: EmbeddingService | None = None
redis_client = None


def build_chunker(cfg):
    """Pick the chunking strategy.

    `fixed` is the approach ADR-006 rejected, kept selectable so the comparison
    in that document is reproducible: set `CHUNKER=fixed`, re-ingest, and the
    grab-bag chunks that lost a water-recovery query to an altitude/power/
    attitude chunk come back.
    """
    if cfg.CHUNKER == "fixed":
        return FixedSizeChunker(cfg.CHUNK_SIZE_WORDS, cfg.CHUNK_OVERLAP_WORDS)
    if cfg.CHUNKER != "structural":
        raise ValueError(
            f"Unknown CHUNKER {cfg.CHUNKER!r}; expected 'structural' or 'fixed'"
        )
    return StructuralChunker(cfg.CHUNK_SIZE_WORDS, cfg.CHUNK_OVERLAP_WORDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global embedding_service, redis_client

    init_db()

    embedding_service = EmbeddingService(config)
    await embedding_service.start()

    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), using in-memory fallback")
        redis_client = None

    vector_store = ChromaVectorStore(config.CHROMA_PATH)
    chunker = build_chunker(config)
    ingest_svc = IngestService(chunker, embedding_service, vector_store)
    retrieval = RetrievalOrchestrator(embedding_service, vector_store, config)
    cache = CacheLayer(config, redis_client)
    llm_svc = LLMService(config)
    router_svc = ModelRouter(llm_svc, config)
    rate_limiter = TokenBucketRateLimiter(config, redis_client)
    observability = ObservabilityService(models.engine)
    pruned = observability.prune_traces(config.TRACE_RETENTION_HOURS)
    if pruned:
        logger.info(f"Pruned {pruned} traces older than {config.TRACE_RETENTION_HOURS}h")

    if config.SEED_SAMPLES:
        await seed_samples(ingest_svc, models.engine)

    documents.set_ingest_service(ingest_svc, rate_limiter)
    query.set_services(retrieval, cache, router_svc, rate_limiter, observability)
    metrics.set_observability(observability)
    traces.set_observability(observability)

    yield

    await embedding_service.stop()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(title="Glasshouse", lifespan=lifespan)

# An explicit allowlist, not "*". The default covers the Vite dev server; a
# production build served from this same process needs no CORS at all. Set
# CORS_ORIGINS="*" to opt back into the wide-open behaviour deliberately.
_origins = [o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
async def health():
    """Liveness plus the state of the two optional dependencies.

    Redis being absent is a *healthy* state here — the cache and limiter both
    have in-memory fallbacks — so it is reported without failing the check.
    """
    redis_state = "disabled"
    if redis_client is not None:
        try:
            await redis_client.ping()
            redis_state = "ok"
        except Exception:
            redis_state = "unavailable"
    elif config.REDIS_URL:
        redis_state = "unavailable"

    return {
        "status": "ok",
        "redis": redis_state,
        "embeddings": config.EMBEDDING_PROVIDER,
        "chunker": config.CHUNKER,
        "provider": config.LLM_PROVIDER,
        "default_tier": config.LLM_DEFAULT_TIER,
        # Resolved server-side so the UI shows the model that will actually
        # answer. Hardcoding "Haiku / Sonnet / Opus" in the frontend goes stale
        # the moment LLM_BASE_URL points somewhere else.
        "models": resolve_models(config),
    }


app.include_router(documents.router)
app.include_router(query.router)
app.include_router(metrics.router)
app.include_router(traces.router)

frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
