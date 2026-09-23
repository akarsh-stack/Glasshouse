from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379"
    DATABASE_URL: str = "sqlite:///./glasshouse.db"
    CHROMA_PATH: str = "./chroma_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    # "onnx" | "sentence-transformers" | "openai". All three produce real
    # embeddings; "onnx" and "sentence-transformers" run the same MiniLM model
    # (384-dim) locally, the first via onnxruntime and the second via PyTorch.
    # onnx is the default because it needs no torch install — see ADR-005.
    EMBEDDING_PROVIDER: str = "onnx"
    OPENAI_API_KEY: str = ""
    # Tier used when the query carries no hint and the length heuristic doesn't
    # promote it. Read by ModelRouter.route.
    LLM_DEFAULT_TIER: str = "fast"
    # "anthropic" | "openai". "openai" means *OpenAI-compatible*, which is the
    # wire format Groq, Google AI Studio, OpenRouter and Ollama all speak — set
    # LLM_BASE_URL to point at whichever one you have a key for.
    LLM_PROVIDER: str = "anthropic"
    LLM_BASE_URL: str = ""
    # Falls back to ANTHROPIC_API_KEY when blank, so the Anthropic path needs no
    # extra setting.
    LLM_API_KEY: str = ""
    # Blank means "use the provider's default for this tier" — see
    # DEFAULT_MODELS in services/llm.py.
    LLM_MODEL_FAST: str = ""
    LLM_MODEL_QUALITY: str = ""
    LLM_MODEL_DEEP: str = ""
    # Per-attempt wall clock for one tier. The router has up to three tiers to
    # try, so worst-case time to a surfaced error is ~3x this. Kept well under a
    # typical 60s client timeout for that reason.
    LLM_TIMEOUT_S: float = 15.0
    LLM_MAX_TOKENS: int = 2048
    # Derived from measurement, not taste — see docs/adr/002-semantic-cache-tier.md
    # for the numbers. Measured bands on this corpus with all-MiniLM-L6-v2:
    #   same intent, reworded    0.67 - 0.96
    #   related but distinct     0.35 - 0.40   <- must never hit
    #   unrelated                below 0.10
    # 0.95 (the intuitive "very similar" value) fires almost never, so the tier
    # was dead code. 0.80 sits twice as high as the related-but-distinct band
    # while catching most natural rewordings — high precision, moderate recall.
    # Negation is handled by a separate lexical guard in services/cache.py,
    # because it is *not* separable by cosine at any threshold.
    SEMANTIC_CACHE_THRESHOLD: float = 0.80
    CACHE_TTL: int = 3600
    # Traces older than this are pruned at startup. Must be >= the widest
    # metrics window (7d) or that view silently loses its oldest slice.
    TRACE_RETENTION_HOURS: int = 24 * 30
    # Per-session bucket: the tight, per-user limit.
    RATE_LIMIT_TOKENS: int = 100
    RATE_LIMIT_REFILL_RATE: float = 10.0
    # Per-IP bucket: a looser backstop, because `session_id` comes from the
    # client and rotating it would otherwise reset the limit. Sized well above
    # the session bucket so ordinary shared egress (an office, a NAT) is not
    # throttled, while a single host cycling session ids still is.
    RATE_LIMIT_IP_TOKENS: int = 400
    RATE_LIMIT_IP_REFILL_RATE: float = 40.0
    # Ingestion runs the embedding model over whatever arrives and holds the
    # whole upload in memory, so it needs a ceiling. 20 MB covers a large PDF.
    MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024
    # Ingest samples/ at startup when the store is empty. Off by default so
    # local development doesn't re-ingest on every boot; on for deploys, where
    # a host without a persistent disk otherwise greets every visitor with an
    # empty corpus and no starter questions.
    SEED_SAMPLES: bool = False
    # Ingestion is far more expensive per request than a query, so it spends
    # more of the same bucket.
    UPLOAD_TOKEN_COST: int = 25
    # Browser origins allowed to call the API. The default covers the Vite dev
    # server; a single-origin build (backend serving frontend/dist) needs none.
    # "*" is accepted but should not be a default — see main.py.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    MICRO_BATCH_WINDOW_MS: int = 30
    # "structural" | "fixed". `fixed` is the approach ADR-006 rejected, kept
    # selectable so its measurements can be reproduced rather than taken on
    # faith. See build_chunker in main.py.
    CHUNKER: str = "structural"
    CHUNK_SIZE_WORDS: int = 220
    CHUNK_OVERLAP_WORDS: int = 40
    TOP_K: int = 5
    # Absolute floor only — near-zero cosine really is noise. The primary gate is
    # RELATIVE_SCORE_RATIO: keep chunks scoring within this fraction of the best
    # hit. Measured on this corpus, correct matches sit at 0.2-0.5 absolute, so an
    # absolute threshold above ~0.15 discards true positives.
    SCORE_THRESHOLD: float = 0.08
    RELATIVE_SCORE_RATIO: float = 0.55
    TOKEN_BUDGET: int = 3000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


config = Config()
