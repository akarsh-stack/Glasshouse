"""HTTP surface: upload limits, health, and error status codes.

`POST /api/documents` had no size cap, no rate limit and no auth, while reading
the whole upload into memory — so the one endpoint that runs an embedding model
over arbitrary input was the one endpoint nothing guarded. The rate limiter's
own docstring claims it is "the only layer allowed to say no before CPU is
spent", which was true only of `/api/query`.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.models import SQLModel


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A real app instance, pointed at throwaway storage."""
    import app.config as config_module

    test_config = Config(
        ANTHROPIC_API_KEY="test-key",
        DATABASE_URL=f"sqlite:///{tmp_path / 'test.db'}",
        CHROMA_PATH=str(tmp_path / "chroma"),
        REDIS_URL="redis://127.0.0.1:1",  # unreachable on purpose
        MAX_UPLOAD_BYTES=1024,
    )
    monkeypatch.setattr(config_module, "config", test_config)

    import app.models as models_module
    from sqlmodel import create_engine

    engine = create_engine(
        test_config.DATABASE_URL, connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(models_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health_reports_ok(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_health_names_the_optional_dependencies(self, client):
        """Redis is unreachable here, and that is a healthy state, not an error."""
        body = client.get("/api/health").json()
        assert body["redis"] == "unavailable"
        assert body["status"] == "ok"


class TestUploadLimits:
    def test_an_oversized_upload_is_refused(self, client):
        big = b"# Title\n\n" + (b"word " * 5000)
        res = client.post("/api/documents", files={"file": ("big.md", big, "text/markdown")})
        assert res.status_code == 413

    def test_the_limit_is_reported_in_the_error(self, client):
        big = b"# Title\n\n" + (b"word " * 5000)
        detail = client.post(
            "/api/documents", files={"file": ("big.md", big, "text/markdown")}
        ).json()["detail"]
        assert "1024" in str(detail)

    def test_an_upload_within_the_limit_still_works(self, client):
        small = b"# Station vitals\n\nThe station orbits at 412 kilometres altitude.\n"
        res = client.post("/api/documents", files={"file": ("ok.md", small, "text/markdown")})
        assert res.status_code == 200
        assert res.json()["chunk_count"] >= 1

    def test_an_unreadable_file_is_a_400_not_a_500(self, client):
        res = client.post(
            "/api/documents", files={"file": ("broken.pdf", b"not a pdf", "application/pdf")}
        )
        assert res.status_code == 400

    def test_an_empty_file_is_a_400(self, client):
        res = client.post("/api/documents", files={"file": ("empty.md", b"", "text/plain")})
        assert res.status_code == 400


class TestUploadIsRateLimited:
    def test_repeated_uploads_are_eventually_shed(self, client):
        statuses = []
        for i in range(80):
            body = f"# Doc {i}\n\nUnique body text number {i} for the station log.\n".encode()
            statuses.append(
                client.post(
                    "/api/documents", files={"file": (f"d{i}.md", body, "text/markdown")}
                ).status_code
            )
        assert 429 in statuses, (
            "ingestion runs an embedding model over arbitrary input and must be "
            f"behind the limiter; got {sorted(set(statuses))}"
        )
