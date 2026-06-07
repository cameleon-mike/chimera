"""Tests for Prometheus /metrics and enriched /health (Session 6.2)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge import queue as bridge_queue


@pytest.fixture
def client():
    return TestClient(app)


def test_metrics_endpoint_200_plaintext(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


def test_metrics_contains_requests_total(client):
    resp = client.get("/metrics")
    assert "chimera_requests_total" in resp.text


def test_metrics_contains_request_duration(client):
    resp = client.get("/metrics")
    assert "chimera_request_duration_seconds" in resp.text


def test_middleware_increments_counter(client):
    client.get("/health")
    resp = client.get("/metrics")
    assert "chimera_requests_total" in resp.text
    assert 'endpoint="/health"' in resp.text


def test_health_has_redis_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "redis" in body["checks"]
    assert "status" in body["checks"]["redis"]


def test_health_has_sqlite_check(client):
    resp = client.get("/health")
    body = resp.json()
    assert "sqlite" in body["checks"]
    assert "status" in body["checks"]["sqlite"]


def test_health_degraded_when_redis_down(client, monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(bridge_queue, "_redis_conn", boom)
    resp = client.get("/health")
    body = resp.json()
    assert body["checks"]["redis"]["status"] == "error"
    assert body["status"] == "degraded"


def test_uptime_positive(client):
    resp = client.get("/health")
    assert resp.json()["uptime_seconds"] >= 0
