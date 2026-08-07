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

COST = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5":  (3.0, 15.0),
    "claude-opus-5":    (5.0, 25.0),
}


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

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()


class LLMService:
    def __init__(self, config):
        self.config = config
        self._breakers = {tier: CircuitBreaker() for tier in TIERS}
        import anthropic
        # max_retries=0 is deliberate: the ModelRouter's fallback chain *is* the
        # retry policy. Letting the SDK also retry means a dead tier is attempted
        # 3x before the router even learns it failed, which turns a fast failover
        # into a slow one and hides the failure from the trace.
        self._client = anthropic.AsyncAnthropic(
            api_key=config.ANTHROPIC_API_KEY,
            timeout=config.LLM_TIMEOUT_S,
            max_retries=0,
        )

    async def generate_stream(
        self, prompt: str, tier: str, context_chunks: list[dict]
    ) -> AsyncGenerator[dict, None]:
        model = TIERS.get(tier, TIERS["quality"])
        breaker = self._breakers.get(tier, CircuitBreaker())

        if breaker.is_open():
            raise RuntimeError(f"Circuit breaker open for tier {tier}")

        context = "\n\n".join(c["text"] for c in context_chunks)
        system = "You are a helpful assistant. Use the provided context to answer questions accurately."
        user_msg = f"Context:\n{context}\n\nQuestion: {prompt}" if context else prompt

        tokens_in = 0
        tokens_out = 0
        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "chunk", "text": text}

                msg = await stream.get_final_message()
                tokens_in = msg.usage.input_tokens
                tokens_out = msg.usage.output_tokens

            breaker.record_success()
            cin, cout = COST.get(model, (3.0, 15.0))
            cost = (tokens_in * cin + tokens_out * cout) / 1_000_000
            yield {
                "type": "done",
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost,
                "model": model,
            }
        except Exception as e:
            breaker.record_failure()
            logger.error(f"LLM error tier={tier} model={model}: {e}")
            raise
