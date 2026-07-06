from fastapi.testclient import TestClient

from src.main import app


def test_healthz_returns_ok() -> None:
    client = TestClient(app=app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_sets_request_id_header() -> None:
    """RequestCtxMiddleware should stamp X-Request-ID on every response."""
    client = TestClient(app=app)
    response = client.get("/healthz")
    assert "x-request-id" in {k.lower() for k in response.headers.keys()}
    assert response.headers["x-request-id"]
