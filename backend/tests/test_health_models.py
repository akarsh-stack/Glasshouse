"""`/api/health` reports which model each tier resolves to.

The tier switcher in the UI showed three words and nothing else, so picking
"deep" gave no indication of what it would actually do. The names are already
resolved server-side by `resolve_models`; publishing them means the UI can show
the real model rather than a hardcoded guess that drifts the moment someone
points LLM_BASE_URL at a different provider.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.models import SQLModel


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.config as config_module

    test_config = Config(
        _env_file=None,
        ANTHROPIC_API_KEY="test-key",
        DATABASE_URL=f"sqlite:///{tmp_path / 'h.db'}",
        CHROMA_PATH=str(tmp_path / "chroma"),
        REDIS_URL="redis://127.0.0.1:1",
    )
    monkeypatch.setattr(config_module, "config", test_config)

    import app.models as models_module
    from sqlmodel import create_engine

    engine = create_engine(test_config.DATABASE_URL, connect_args={"check_same_thread": False})
    monkeypatch.setattr(models_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    import app.main as main_module

    # `app/main.py` does `from .config import config`, which binds the object at
    # import time. An earlier test in the session has already imported it, so
    # patching `app.config.config` alone leaves main holding the real one — and
    # this file's assertions would then be read off the developer's own .env.
    # Patch main's binding too, or these tests pass alone and fail in the suite.
    monkeypatch.setattr(main_module, "config", test_config)

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestHealthModels:
    def test_every_tier_is_reported(self, client):
        models = client.get("/api/health").json()["models"]
        assert set(models) == {"fast", "quality", "deep"}

    def test_the_defaults_are_the_claude_tiers(self, client):
        models = client.get("/api/health").json()["models"]
        assert models["fast"] == "claude-haiku-4-5"
        assert models["deep"] == "claude-opus-5"

    def test_the_configured_default_tier_is_reported(self, client):
        body = client.get("/api/health").json()
        assert body["default_tier"] in {"fast", "quality", "deep"}

    def test_the_provider_is_reported(self, client):
        assert client.get("/api/health").json()["provider"] == "anthropic"
