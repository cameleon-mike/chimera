"""Tests for GET /risk/{domain} endpoint."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

# Override auth for all tests in this module
app.dependency_overrides[require_bearer] = lambda: "test-token"

client = TestClient(app)


def _make_risk_event(
    domain: str,
    risk_score: float,
    vendors: list[str] | None = None,
    markers: dict | None = None,
    http_status: int = 200,
    ts: str | None = None,
) -> tuple:
    """Return a tuple matching risk_events INSERT order."""
    if ts is None:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "testjob99",
        domain,
        f"https://{domain}/",
        ts,
        http_status,
        risk_score,
        json.dumps(vendors or []),
        json.dumps(markers or {"waf": 0, "captcha": 0, "botdet": 0, "status": 0}),
        1024,
        100,
    )


@pytest.fixture()
def populated_db(tmp_path):
    """Create a temporary risk_db.sqlite with test data and patch _RISK_DB_PATH."""
    db_path = tmp_path / "risk_db.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE risk_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id          TEXT,
            domain          TEXT NOT NULL,
            url             TEXT NOT NULL,
            ts              TEXT NOT NULL,
            http_status     INTEGER,
            risk_score      REAL NOT NULL,
            vendors_json    TEXT,
            markers_json    TEXT,
            response_size   INTEGER,
            duration_ms     INTEGER
        );
    """)
    conn.commit()
    conn.close()

    with patch("bridge.app._RISK_DB_PATH", db_path):
        yield db_path


def _insert_events(db_path: Path, events: list[tuple]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executemany(
        """INSERT INTO risk_events
           (job_id, domain, url, ts, http_status, risk_score,
            vendors_json, markers_json, response_size, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        events,
    )
    conn.commit()
    conn.close()


class TestRiskEndpoint:
    def test_domain_without_data_returns_no_data(self, populated_db):
        resp = client.get(
            "/risk/unknown.com",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "unknown.com"
        assert data["requests"] == 0
        assert data["recommendation"] == "no_data"

    def test_domain_with_data_returns_aggregated_scores(self, populated_db):
        events = [
            _make_risk_event("target.com", 0.3, vendors=["cloudflare"]),
            _make_risk_event("target.com", 0.5, vendors=["akamai"]),
            _make_risk_event("target.com", 0.7, vendors=["cloudflare"]),
        ]
        _insert_events(populated_db, events)

        resp = client.get(
            "/risk/target.com",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["requests"] == 3
        assert data["max_risk"] == pytest.approx(0.7, abs=0.001)
        assert data["avg_risk"] == pytest.approx(0.5, abs=0.001)
        assert "cloudflare" in data["vendors_seen"]
        assert "akamai" in data["vendors_seen"]
        assert data["vendors_seen"] == sorted(data["vendors_seen"])

    def test_invalid_domain_returns_422(self, populated_db):
        resp = client.get(
            "/risk/not_a_valid_domain!",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 422

    def test_window_hours_filters_old_events(self, populated_db):
        # Insert an old event (2 hours ago simulated by old ts)
        old_ts = "2000-01-01T00:00:00Z"
        events = [
            _make_risk_event("filter.com", 0.9, ts=old_ts),
            _make_risk_event("filter.com", 0.1),  # recent
        ]
        _insert_events(populated_db, events)

        resp = client.get(
            "/risk/filter.com?hours=1",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Old event filtered out — only 1 recent event
        assert data["requests"] == 1
        assert data["max_risk"] == pytest.approx(0.1, abs=0.001)

    def test_blocks_counted_correctly(self, populated_db):
        events = [
            _make_risk_event("blocked.com", 0.8, http_status=403),
            _make_risk_event("blocked.com", 0.5, http_status=429),
            _make_risk_event("blocked.com", 0.1, http_status=200),
        ]
        _insert_events(populated_db, events)

        resp = client.get(
            "/risk/blocked.com",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocks"] == 2

    def test_recommendation_high_risk_screenshot(self, populated_db):
        events = [
            _make_risk_event("highrisk.com", 0.9),
            _make_risk_event("highrisk.com", 0.85),
        ]
        _insert_events(populated_db, events)

        resp = client.get(
            "/risk/highrisk.com",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommendation"] == "start_with:screenshot"

    def test_recommendation_medium_risk_crawl4ai(self, populated_db):
        events = [
            _make_risk_event("medium.com", 0.6),
            _make_risk_event("medium.com", 0.55),
        ]
        _insert_events(populated_db, events)

        resp = client.get(
            "/risk/medium.com",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommendation"] == "start_with:crawl4ai"
