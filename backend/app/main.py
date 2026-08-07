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
from .models import engine, init_db
from .chunkers.structural import StructuralChunker
from .services.embedding import EmbeddingService
from .services.vector_store import ChromaVectorStore
from .services.ingestion import IngestService
from .services.retrieval import RetrievalOrchestrator
from .services.cache import CacheLayer
from .services.llm import LLMService
from .services.router import ModelRouter
from .services.rate_limiter import TokenBucketRateLimiter
from .services.observability import ObservabilityService
from .api import documents, query, metrics, traces

logger = logging.getLogger(__name__)

embedding_service: EmbeddingService | None = None
redis_client = None


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
    chunker = StructuralChunker(config.CHUNK_SIZE_WORDS, config.CHUNK_OVERLAP_WORDS)
    ingest_svc = IngestService(chunker, embedding_service, vector_store)
    retrieval = RetrievalOrchestrator(embedding_service, vector_store, config)
    cache = CacheLayer(config, redis_client)
    llm_svc = LLMService(config)
    router_svc = ModelRouter(llm_svc, config)
    rate_limiter = TokenBucketRateLimiter(config, redis_client)
    observability = ObservabilityService(engine)

    documents.set_ingest_service(ingest_svc)
    query.set_services(retrieval, cache, router_svc, rate_limiter, observability)
    metrics.set_observability(observability)
    traces.set_observability(observability)

    yield

    await embedding_service.stop()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(title="Glasshouse", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(query.router)
app.include_router(metrics.router)
app.include_router(traces.router)

frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
