"""Tests for POST /escalate and GET /escalation/policy endpoints."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

app.dependency_overrides[require_bearer] = lambda: "test-token"
client = TestClient(app)

_RISK_EVENTS_DDL = """
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
"""


@pytest.fixture()
def populated_db(tmp_path):
    db = tmp_path / "risk_db.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(_RISK_EVENTS_DDL)
    conn.commit()
    conn.close()
    with patch("bridge.app._RISK_DB_PATH", db):
        yield db


def _insert(db: Path, job_id: str, rows: list[tuple[float, list[str]]]) -> None:
    conn = sqlite3.connect(str(db))
    for score, vendors in rows:
        conn.execute(
            """INSERT INTO risk_events
               (job_id, domain, url, ts, http_status, risk_score,
                vendors_json, markers_json, response_size, duration_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (job_id, "test.com", "https://test.com/", "2026-05-23T00:00:00Z",
             200, score, json.dumps(vendors), "{}", 5000, 100),
        )
    conn.commit()
    conn.close()


def test_no_risk_data_returns_not_needed(populated_db):
    resp = client.post(
        "/escalate",
        json={"job_id": "unknown_job"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["needed"] is False
    assert data["reason"] == "no_risk_data"
    assert data["suggested_tool"] is None


def test_high_risk_job_returns_screenshot_escalation(populated_db):
    _insert(populated_db, "highriskjob", [(0.9, ["cloudflare"]), (0.85, ["akamai"])])
    resp = client.post(
        "/escalate",
        json={"job_id": "highriskjob", "domain": "target.com"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["needed"] is True
    assert data["suggested_tool"] == "screenshot"
    assert "cloudflare" in data["vendors_detected"]


def test_missing_job_id_returns_422(populated_db):
    resp = client.post(
        "/escalate",
        json={"domain": "missing-job.com"},  # no job_id
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 422
