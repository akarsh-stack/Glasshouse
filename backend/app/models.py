from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session
import uuid

from .config import config

# check_same_thread=False because SQLModel sessions are opened both on the event
# loop (trace writes) and in FastAPI's threadpool (sync endpoints).
engine = create_engine(
    config.DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)


def gen_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Naive UTC, the way this schema stores time.

    `datetime.utcnow()` is deprecated, but its timezone-aware replacement would
    change what lands in SQLite: an aware value serialises with an offset while
    every existing row is naive, and the two don't compare. So take the aware
    reading and drop the tzinfo deliberately, rather than by accident.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Document(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    filename: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    status: str = "processing"
    chunk_count: int = 0
    content_hash: str = Field(index=True)


class Chunk(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    text: str
    chunk_index: int
    page_number: Optional[int] = None


class QueryLog(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    query_text: str
    # Indexed: every metrics call filters on it, and this table only grows.
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    cache_status: str = "miss"
    model_used: str = ""
    retrieved_chunk_ids: str = "[]"
    stages_ms: str = "{}"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    fallback_triggered: bool = False
    # Recorded explicitly rather than inferred from an empty model_used — a cache
    # hit also has no model, and conflating the two makes error_rate meaningless.
    error: bool = False
    error_message: str = ""
    # Kept apart from `error`: a 429 means the rate limiter did its job.
    rate_limited: bool = False


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
