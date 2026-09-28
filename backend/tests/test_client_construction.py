"""Both provider clients can actually be constructed.

Every other provider test injects a fake client, so `_build_client` — and the
`import openai` inside it — never ran. `openai` was pip-installed locally when
the provider was added and never written into requirements.txt, so the container
had no such module and startup died with ModuleNotFoundError. CI missed it too:
the Docker smoke test runs with no env vars, so LLM_PROVIDER defaulted to
`anthropic` and the openai branch was never touched.

These construct the real client for each provider. They make no network calls —
the SDKs don't connect until a request — so what is under test is exactly the
part that broke: that the dependency exists and the client accepts the config.
"""

import pytest

from app.services.llm import LLMService


def cfg(config, **overrides):
    return config.model_copy(update=overrides)


class TestRealClientConstruction:
    def test_the_anthropic_client_builds(self, config):
        svc = LLMService(cfg(config, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="k"))
        assert svc._client is not None

    def test_the_openai_compatible_client_builds(self, config):
        """The exact path that crashed the container on boot."""
        svc = LLMService(
            cfg(
                config,
                LLM_PROVIDER="openai",
                LLM_API_KEY="k",
                LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
        )
        assert svc._client is not None

    def test_the_openai_client_honours_the_base_url(self, config):
        svc = LLMService(
            cfg(config, LLM_PROVIDER="openai", LLM_API_KEY="k", LLM_BASE_URL="https://example.test/v1")
        )
        assert "example.test" in str(svc._client.base_url)

    def test_an_unknown_provider_is_rejected_before_any_import(self, config):
        with pytest.raises(ValueError, match="LLM_PROVIDER"):
            LLMService(cfg(config, LLM_PROVIDER="bedrock"))


class TestEmbeddingProviderImports:
    """`EMBEDDING_PROVIDER=openai` reaches for the same package."""

    def test_the_openai_embedding_backend_can_load_its_client(self, config):
        from app.services.embedding import EmbeddingService

        svc = EmbeddingService(cfg(config, EMBEDDING_PROVIDER="openai", OPENAI_API_KEY="k"))
        svc._load_model()
        assert svc._openai is not None

    def test_an_unknown_embedding_provider_is_rejected(self, config):
        from app.services.embedding import EmbeddingService

        svc = EmbeddingService(cfg(config, EMBEDDING_PROVIDER="nope"))
        with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
            svc._load_model()
