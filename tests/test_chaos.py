"""Chaos tests: unit tests with mocks (no live server, no real redis/network)."""

import pytest
import threading
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer
import bridge.app as bridge_app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def auth_override():
    """Override auth dependency to inject test token, saving/restoring prior state."""
    saved = app.dependency_overrides.get(require_bearer)
    app.dependency_overrides[require_bearer] = lambda: "test-token"
    yield
    if saved is None:
        app.dependency_overrides.pop(require_bearer, None)
    else:
        app.dependency_overrides[require_bearer] = saved


def test_invalid_request_returns_422_not_500(client, auth_override):
    """Invalid tool enum value should return 422, not 500."""
    response = client.post(
        "/run-tool",
        json={"tool": "not_a_real_tool", "url": "http://example.com"},
    )
    assert response.status_code == 422, f"Expected 422, got {response.status_code}"


def test_unknown_endpoint_returns_404_not_500(client):
    """Unknown endpoint should return 404, not 500."""
    response = client.get("/nope_does_not_exist_xyz")
    assert response.status_code == 404


def test_parallel_requests_no_race(client):
    """Parallel /health requests should all succeed (no race conditions)."""
    results = []

    def worker():
        response = client.get("/health")
        results.append(response.status_code)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(code == 200 for code in results)


def test_scraper_timeout_structured(client, auth_override, monkeypatch):
    """POST /run-tool should not 500 and returns structured JSON."""
    # Mock enqueue_job to avoid real redis
    monkeypatch.setattr(bridge_app.q, "enqueue_job", lambda **kw: None)

    response = client.post(
        "/run-tool",
        json={"tool": "crawl4ai", "url": "http://192.0.2.1"},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    body = response.json()
    assert "job_id" in body


def test_stealth_invalid_url_status_error(client, auth_override, monkeypatch):
    """POST /stealth/run with stubbed agent should return error status."""

    class _FakeAgent:
        def __init__(self, *a, **k):
            pass

        def run(self, url, query, source, config, agent_id):
            return {
                "run_id": "sr-chaos01",
                "status": "error",
                "security": {},
                "result": {},
                "report": {},
            }

    monkeypatch.setattr(bridge_app, "StealthAgent", _FakeAgent)

    response = client.post(
        "/stealth/run",
        json={"url": "http://invalid.tld", "source": "chaos"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["run_id"] == "sr-chaos01"


def test_public_endpoints_no_auth(client):
    """Public endpoints /health and /metrics should return 200 without auth."""
    response = client.get("/health")
    assert response.status_code == 200

    response = client.get("/metrics")
    assert response.status_code == 200
