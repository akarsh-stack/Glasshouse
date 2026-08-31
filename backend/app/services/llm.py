import asyncio
import logging
import time
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# Model IDs and $/1M-token (input, output) rates verified against the Anthropic
# API reference at build time (July 2026). Sonnet 5 has intro pricing of $2/$10
# through 2026-08-31; we use the standard sticker rates for cost estimates.
TIERS = {
    "fast": "claude-haiku-4-5",
    "quality": "claude-sonnet-5",
    "deep": "claude-opus-5",
}

# Per-tier defaults by provider. "openai" means *OpenAI-compatible*, and the
# defaults are Groq's — free, no card, and the fastest of the free options. Any
# of them can be overridden with LLM_MODEL_FAST / _QUALITY / _DEEP, which is how
# you point the same code path at Google AI Studio, OpenRouter or a local Ollama.
DEFAULT_MODELS = {
    "anthropic": dict(TIERS),
    "openai": {
        "fast": "llama-3.1-8b-instant",
        "quality": "llama-3.3-70b-versatile",
        "deep": "openai/gpt-oss-120b",
    },
}

# $ per 1M tokens (input, output), verified against the Anthropic API reference
# at build time (July 2026). Models absent from this table are priced at zero
# rather than guessed — see cost_for.
COST = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5":  (3.0, 15.0),
    "claude-opus-5":    (5.0, 25.0),
}


def resolve_models(config) -> dict[str, str]:
    """Tier -> model id, provider defaults with per-tier overrides."""
    provider = config.LLM_PROVIDER
    if provider not in DEFAULT_MODELS:
        raise ValueError(
            f"Unknown LLM_PROVIDER {provider!r}; expected one of {sorted(DEFAULT_MODELS)}"
        )
    overrides = {
        "fast": config.LLM_MODEL_FAST,
        "quality": config.LLM_MODEL_QUALITY,
        "deep": config.LLM_MODEL_DEEP,
    }
    return {
        tier: overrides[tier] or default
        for tier, default in DEFAULT_MODELS[provider].items()
    }


def cost_for(model: str, tokens_in: int, tokens_out: int) -> float:
    """USD for one call, or 0.0 for a model with no published rate here.

    Unknown models used to inherit Sonnet's rate as a default, which invented a
    dollar figure for a free-tier Llama call and put it on the receipt. A
    receipt that guesses is worse than one that reads $0.0000.
    """
    rate_in, rate_out = COST.get(model, (0.0, 0.0))
    return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000


# HTTP statuses where retrying — on this tier or any other — cannot help.
# A bad key, a malformed request or an unknown model fails identically
# everywhere, so walking the fallback chain only multiplies the latency and
# buries the real message behind "all tiers failed".
_PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 422})


def is_retryable(error: Exception) -> bool:
    """Is this worth trying on another tier?

    Anything without a status — a timeout, a dropped socket — is retryable:
    those are exactly the transient faults the fallback chain exists for.
    """
    status = getattr(error, "status_code", None)
    if status is None:
        return True
    return int(status) not in _PERMANENT_STATUSES


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self):
        self._failures = 0
        self._opened_at = None

    def record_failure(self, error: Exception | None = None):
        # A breaker exists to protect a *struggling upstream*. A rejected
        # request means the upstream is healthy and the request was wrong, so
        # counting it would open the circuit on a problem cooling off won't fix.
        if error is not None and not is_retryable(error):
            return
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()


_SYSTEM_GROUNDED = """You answer questions using only the numbered context passages provided.

Rules:
- Ground every claim in the context. Do not use outside knowledge, even if you are confident it is correct.
- Cite the passages you used with their bracketed numbers, like [1] or [2, 3].
- If the context does not contain the answer, say you don't know and name what is missing. A wrong answer is far worse than an admitted gap.
- Do not speculate, and do not pad a thin answer to make it look complete."""

_SYSTEM_NO_CONTEXT = """You are answering with no context passages available: retrieval returned nothing relevant.

Say plainly that you have no context for this question and that the answer below comes from general knowledge rather than the user's documents. Keep it brief."""


def build_prompt(query: str, context_chunks: list[dict]) -> tuple[str, str]:
    """(system, user) for one RAG turn.

    Passages are numbered so the answer can cite them, which is what makes the
    chunk cards in the UI verifiable rather than decorative. Without grounding
    instructions the model answers a retrieval miss from training data — the
    worst failure a RAG system has, because it looks authoritative.
    """
    if not context_chunks:
        return _SYSTEM_NO_CONTEXT, f"Question: {query}"

    blocks = []
    for i, chunk in enumerate(context_chunks, 1):
        page = chunk.get("page_number")
        locator = f" (p. {page})" if page else ""
        blocks.append(f"[{i}]{locator} {chunk['text']}")

    user = "Context passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {query}"
    return _SYSTEM_GROUNDED, user


class LLMService:
    def __init__(self, config, client=None):
        self.config = config
        self.models = resolve_models(config)
        self._breakers = {tier: CircuitBreaker() for tier in self.models}
        self._client = client if client is not None else self._build_client(config)

    def _build_client(self, config):
        # max_retries=0 is deliberate on both paths: the ModelRouter's fallback
        # chain *is* the retry policy. Letting the SDK also retry means a dead
        # tier is attempted 3x before the router even learns it failed, which
        # turns a fast failover into a slow one and hides it from the trace.
        if config.LLM_PROVIDER == "openai":
            import openai

            return openai.AsyncOpenAI(
                api_key=config.LLM_API_KEY or config.OPENAI_API_KEY,
                base_url=config.LLM_BASE_URL or None,
                timeout=config.LLM_TIMEOUT_S,
                max_retries=0,
            )

        import anthropic

        return anthropic.AsyncAnthropic(
            api_key=config.LLM_API_KEY or config.ANTHROPIC_API_KEY,
            base_url=config.LLM_BASE_URL or None,
            timeout=config.LLM_TIMEOUT_S,
            max_retries=0,
        )

    async def generate_stream(
        self, prompt: str, tier: str, context_chunks: list[dict]
    ) -> AsyncGenerator[dict, None]:
        model = self.models.get(tier) or self.models["quality"]
        breaker = self._breakers.get(tier, CircuitBreaker())

        if breaker.is_open():
            raise RuntimeError(f"Circuit breaker open for tier {tier}")

        system, user_msg = build_prompt(prompt, context_chunks)
        backend = (
            self._stream_openai
            if self.config.LLM_PROVIDER == "openai"
            else self._stream_anthropic
        )

        try:
            tokens_in = tokens_out = 0
            async for event in backend(model, system, user_msg):
                if event["type"] == "chunk":
                    yield event
                else:
                    tokens_in, tokens_out = event["tokens_in"], event["tokens_out"]

            breaker.record_success()
            yield {
                "type": "done",
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_for(model, tokens_in, tokens_out),
                "model": model,
            }
        except Exception as e:
            breaker.record_failure(e)
            logger.error(f"LLM error tier={tier} model={model}: {e}")
            raise

    async def _stream_anthropic(self, model, system, user_msg):
        async with self._client.messages.stream(
            model=model,
            max_tokens=self.config.LLM_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            async for text in stream.text_stream:
                yield {"type": "chunk", "text": text}
            msg = await stream.get_final_message()
            yield {
                "type": "usage",
                "tokens_in": msg.usage.input_tokens,
                "tokens_out": msg.usage.output_tokens,
            }

    async def _stream_openai(self, model, system, user_msg):
        """OpenAI-compatible chat completions: Groq, Google AI Studio, OpenRouter, Ollama."""
        stream = await self._client.chat.completions.create(
            model=model,
            max_tokens=self.config.LLM_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            stream=True,
            # Usage is omitted from streamed responses unless asked for. Servers
            # that ignore this option simply never send it, handled below.
            stream_options={"include_usage": True},
        )

        tokens_in = tokens_out = 0
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield {"type": "chunk", "text": text}
            usage = getattr(chunk, "usage", None)
            if usage:
                tokens_in = getattr(usage, "prompt_tokens", 0) or 0
                tokens_out = getattr(usage, "completion_tokens", 0) or 0

        yield {"type": "usage", "tokens_in": tokens_in, "tokens_out": tokens_out}
