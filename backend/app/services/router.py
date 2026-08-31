import logging
from typing import AsyncGenerator

from .llm import is_retryable

logger = logging.getLogger(__name__)

TIERS = ["fast", "quality", "deep"]


class ModelRouter:
    def __init__(self, llm_service, config):
        self.llm = llm_service
        self.config = config

    def route(self, query_text: str, user_tier_hint: str | None = None) -> str:
        """Explicit hint wins; otherwise the configured default, promoted for
        long queries.

        The default comes from `LLM_DEFAULT_TIER` rather than a literal, which
        is what that setting was always for — it shipped in config.py and
        .env.example and was read by nothing.
        """
        if user_tier_hint and user_tier_hint in TIERS:
            return user_tier_hint
        default = self.config.LLM_DEFAULT_TIER
        if default not in TIERS:
            logger.warning(f"LLM_DEFAULT_TIER {default!r} is not a tier; using 'fast'")
            default = "fast"
        # A long query carries more context to reason over, so it is promoted
        # one step — but never demoted below the configured floor.
        if len(query_text.split()) >= 50 and TIERS.index(default) < TIERS.index("quality"):
            return "quality"
        return default

    async def generate_with_fallback(
        self,
        prompt: str,
        tier: str,
        context_chunks: list[dict],
        trace,
    ) -> AsyncGenerator[dict, None]:
        tier_order = TIERS
        start_idx = tier_order.index(tier) if tier in tier_order else 1
        attempts = [tier_order[start_idx]] + [
            t for i, t in enumerate(tier_order) if i != start_idx
        ]

        last_err = None
        for attempt_tier in attempts:
            # Once a tier has emitted text to the client we are committed to it.
            # Falling back mid-stream would append a second, complete answer to a
            # partial one, and the user would read the concatenation as a single
            # garbled response. A failure after first token is surfaced as an
            # error instead — truncated but coherent beats silently doubled.
            emitted = False
            try:
                async for event in self.llm.generate_stream(prompt, attempt_tier, context_chunks):
                    if event.get("type") == "chunk":
                        emitted = True
                    if attempt_tier != tier and trace is not None:
                        trace.fallback_triggered = True
                    yield event
                return
            except Exception as e:
                last_err = e
                if emitted:
                    logger.error(
                        f"Tier {attempt_tier} failed after streaming started; "
                        f"not falling back: {e}"
                    )
                    raise RuntimeError(
                        f"Generation failed partway through on tier {attempt_tier}: {e}"
                    ) from e
                if not is_retryable(e):
                    # Same credentials, same request shape, same outcome on every
                    # tier. Walking the chain would triple the latency and then
                    # report "all tiers failed", hiding the one useful message.
                    logger.error(f"Tier {attempt_tier} failed permanently, not falling back: {e}")
                    raise
                logger.warning(f"Tier {attempt_tier} failed: {e}, trying next")

        raise RuntimeError(f"All tiers failed. Last error: {last_err}")
