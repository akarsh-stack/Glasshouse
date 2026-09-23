from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, DateTime, TypeDecorator
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
    """Timezone-aware UTC.

    This previously dropped the tzinfo to keep storage naive, on the reasoning
    that an aware value would stop comparing against existing rows. That traded
    correctness for compatibility with data this project documents as
    regenerable — and it wasn't even compatible: newer `sqlmodel` rejects naive
    datetimes for a `DateTime` column, so the naive version passed locally and
    failed in CI on every test that wrote a trace.

    Columns are declared `DateTime(timezone=True)` so the offset survives the
    round trip rather than being silently discarded on read.
    """
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """A UTC datetime that survives SQLite.

    SQLite has no timezone-aware type: SQLAlchemy writes the value and hands
    back a *naive* datetime on read, even with `DateTime(timezone=True)`. So
    every write is normalised to UTC, and every read has UTC re-attached —
    without this, `GET /api/traces/{id}` returns a timestamp with no offset and
    a client has no way to know which zone it is in.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; use utcnow()")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Document(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    filename: str
    # timezone=True so the offset survives the round trip; without it
    # SQLAlchemy strips tzinfo on read and reads come back naive.
    uploaded_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(UtcDateTime())
    )
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
    timestamp: datetime = Field(
        default_factory=utcnow, sa_column=Column(UtcDateTime(), index=True)
    )
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
