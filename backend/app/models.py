from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session
import uuid

DATABASE_URL = "sqlite:///./glasshouse.db"
engine = create_engine(DATABASE_URL, echo=False)


def gen_id() -> str:
    return str(uuid.uuid4())


class Document(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    filename: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "processing"
    chunk_count: int = 0
    content_hash: str


class Chunk(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    document_id: str = Field(foreign_key="document.id")
    text: str
    chunk_index: int
    page_number: Optional[int] = None


class QueryLog(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    query_text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
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


class CacheEntry(SQLModel, table=True):
    id: str = Field(default_factory=gen_id, primary_key=True)
    normalized_query: str
    response_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    ttl: int = 3600
    hit_count: int = 0


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
