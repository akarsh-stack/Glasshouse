from pydantic_settings import BaseSettings


class Config(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379"
    CHROMA_PATH: str = "./chroma_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    # "onnx" | "sentence-transformers" | "openai". All three produce real
    # embeddings; "onnx" and "sentence-transformers" run the same MiniLM model
    # (384-dim) locally, the first via onnxruntime and the second via PyTorch.
    # onnx is the default because it needs no torch install — see ADR-005.
    EMBEDDING_PROVIDER: str = "onnx"
    OPENAI_API_KEY: str = ""
    LLM_DEFAULT_TIER: str = "quality"
    # Per-attempt wall clock for one tier. The router has up to three tiers to
    # try, so worst-case time to a surfaced error is ~3x this. Kept well under a
    # typical 60s client timeout for that reason.
    LLM_TIMEOUT_S: float = 15.0
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
    RATE_LIMIT_TOKENS: int = 100
    RATE_LIMIT_REFILL_RATE: float = 10.0
    MICRO_BATCH_WINDOW_MS: int = 30
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

    class Config:
        env_file = ".env"


config = Config()
