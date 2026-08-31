"""Provider abstraction for the generation step.

The service was hardwired to `anthropic.AsyncAnthropic`, so running the demo
required a funded Anthropic account. Every free-tier provider worth using —
Groq, Google AI Studio, OpenRouter, a local Ollama — speaks the OpenAI wire
format, so one OpenAI-compatible path plus a configurable base URL reaches all
of them.

The tier names (`fast`/`quality`/`deep`) stay; only what each maps to moves.
"""

from types import SimpleNamespace

import pytest

from app.services.llm import LLMService, cost_for, resolve_models


def cfg(config, **overrides):
    return config.model_copy(update=overrides)


class TestModelResolution:
    def test_anthropic_defaults_to_the_claude_tiers(self, config):
        models = resolve_models(cfg(config, LLM_PROVIDER="anthropic"))
        assert models == {
            "fast": "claude-haiku-4-5",
            "quality": "claude-sonnet-5",
            "deep": "claude-opus-5",
        }

    def test_openai_compatible_defaults_to_groq_models(self, config):
        models = resolve_models(cfg(config, LLM_PROVIDER="openai"))
        assert set(models) == {"fast", "quality", "deep"}
        assert all(models.values()), "every tier needs a model id"
        assert "claude" not in " ".join(models.values())

    def test_an_explicit_model_overrides_the_default(self, config):
        models = resolve_models(
            cfg(config, LLM_PROVIDER="openai", LLM_MODEL_QUALITY="qwen/qwen3-32b")
        )
        assert models["quality"] == "qwen/qwen3-32b"

    def test_overriding_one_tier_leaves_the_others_alone(self, config):
        base = resolve_models(cfg(config, LLM_PROVIDER="openai"))
        models = resolve_models(cfg(config, LLM_PROVIDER="openai", LLM_MODEL_FAST="x"))
        assert models["fast"] == "x"
        assert models["deep"] == base["deep"]

    def test_an_unknown_provider_is_rejected_by_name(self, config):
        with pytest.raises(ValueError, match="LLM_PROVIDER"):
            resolve_models(cfg(config, LLM_PROVIDER="bedrock"))


class TestCostAccounting:
    def test_a_known_claude_model_is_priced(self):
        # 1M in + 1M out on Haiku at $1/$5.
        assert cost_for("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.0)

    def test_an_unpriced_model_reports_zero_not_a_guess(self):
        """Free-tier models cost nothing; inventing Sonnet's rate would be a lie."""
        assert cost_for("llama-3.3-70b-versatile", 1_000_000, 1_000_000) == 0.0

    def test_zero_tokens_costs_nothing(self):
        assert cost_for("claude-opus-5", 0, 0) == 0.0


def fake_openai_client(text_parts: list[str], usage=None, captured=None):
    """Mimics AsyncOpenAI.chat.completions.create(stream=True)."""

    async def _stream():
        for part in text_parts:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=part))],
                usage=None,
            )
        yield SimpleNamespace(choices=[], usage=usage)

    async def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return _stream()

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class TestOpenAICompatibleStreaming:
    async def test_text_deltas_are_emitted_as_chunks(self, config):
        svc = LLMService(
            cfg(config, LLM_PROVIDER="openai"),
            client=fake_openai_client(["Ninety-", "three ", "percent."]),
        )
        events = [e async for e in svc.generate_stream("q", "fast", [])]
        assert "".join(e["text"] for e in events if e["type"] == "chunk") == "Ninety-three percent."

    async def test_usage_is_reported_when_the_provider_sends_it(self, config):
        usage = SimpleNamespace(prompt_tokens=42, completion_tokens=7)
        svc = LLMService(
            cfg(config, LLM_PROVIDER="openai"), client=fake_openai_client(["hi"], usage=usage)
        )
        done = [e async for e in svc.generate_stream("q", "fast", [])][-1]
        assert done["type"] == "done"
        assert (done["tokens_in"], done["tokens_out"]) == (42, 7)

    async def test_missing_usage_degrades_to_zero_rather_than_crashing(self, config):
        """Not every OpenAI-compatible server returns usage on a stream."""
        svc = LLMService(cfg(config, LLM_PROVIDER="openai"), client=fake_openai_client(["hi"]))
        done = [e async for e in svc.generate_stream("q", "fast", [])][-1]
        assert done["tokens_in"] == 0 and done["tokens_out"] == 0

    async def test_usage_is_requested_explicitly(self, config):
        captured: dict = {}
        svc = LLMService(
            cfg(config, LLM_PROVIDER="openai"),
            client=fake_openai_client(["hi"], captured=captured),
        )
        [e async for e in svc.generate_stream("q", "fast", [])]
        assert captured["stream"] is True
        assert captured["stream_options"] == {"include_usage": True}

    async def test_the_grounding_prompt_is_sent_as_a_system_message(self, config):
        captured: dict = {}
        svc = LLMService(
            cfg(config, LLM_PROVIDER="openai"),
            client=fake_openai_client(["hi"], captured=captured),
        )
        chunks = [{"chunk_id": "c1", "text": "Water recovery is 93 percent.", "page_number": 2}]
        [e async for e in svc.generate_stream("How much water?", "fast", chunks)]
        roles = [m["role"] for m in captured["messages"]]
        assert roles == ["system", "user"]
        assert "don't know" in captured["messages"][0]["content"].lower()
        assert "[1]" in captured["messages"][1]["content"]

    async def test_the_tier_selects_the_configured_model(self, config):
        captured: dict = {}
        svc = LLMService(
            cfg(config, LLM_PROVIDER="openai", LLM_MODEL_DEEP="my/deep-model"),
            client=fake_openai_client(["hi"], captured=captured),
        )
        [e async for e in svc.generate_stream("q", "deep", [])]
        assert captured["model"] == "my/deep-model"
        done = [e async for e in svc.generate_stream("q", "deep", [])][-1]
        assert done["model"] == "my/deep-model"
