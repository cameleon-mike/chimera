"""Tests for GET /dashboard endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

_TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture(autouse=True)
def override_auth():
    _saved = app.dependency_overrides.get(require_bearer)
    app.dependency_overrides[require_bearer] = lambda: _TOKEN
    yield
    if _saved is not None:
        app.dependency_overrides[require_bearer] = _saved
    else:
        app.dependency_overrides.pop(require_bearer, None)


@pytest.fixture
def client():
    return TestClient(app)


# ── Test 1 ──
def test_dashboard_without_token():
    """GET /dashboard sans token → 401."""
    saved = app.dependency_overrides.pop(require_bearer, None)
    try:
        resp = TestClient(app).get("/dashboard")
        assert resp.status_code == 401
    finally:
        if saved is not None:
            app.dependency_overrides[require_bearer] = saved


# ── Test 2 ──
def test_dashboard_returns_200(client):
    """GET /dashboard → 200."""
    resp = client.get("/dashboard", headers=HEADERS)
    assert resp.status_code == 200


# ── Test 3 ──
def test_dashboard_bridge_version_present(client):
    """bridge.version est présent dans la réponse."""
    resp = client.get("/dashboard", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "bridge" in data
    assert "version" in data["bridge"]
    assert isinstance(data["bridge"]["version"], str)


# ── Test 4 ──
def test_dashboard_jobs_queued_non_negative(client):
    """jobs.queued >= 0."""
    resp = client.get("/dashboard", headers=HEADERS)
    data = resp.json()
    assert data["jobs"]["queued"] >= 0


# ── Test 5 ──
def test_dashboard_profiles_has_five_statuses(client):
    """profiles dict contient les 5 statuts."""
    resp = client.get("/dashboard", headers=HEADERS)
    data = resp.json()
    profiles = data["profiles"]
    for key in ("creating", "warming", "ready", "senior", "recycle"):
        assert key in profiles, f"missing profile status: {key}"


# ── Test 6 ──
def test_dashboard_proxy_residential_configured_is_bool(client):
    """proxy.residential_configured est un bool."""
    resp = client.get("/dashboard", headers=HEADERS)
    data = resp.json()
    assert isinstance(data["proxy"]["residential_configured"], bool)
