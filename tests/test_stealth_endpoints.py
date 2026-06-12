"""Tests for the 6 stealth bridge endpoints (S4)."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import bridge.app as _app_module
    from bridge.app import app

    tmp_db = tmp_path / "risk_db.sqlite"
    _app_module._RISK_DB_PATH = tmp_db
    _app_module._init_risk_db()

    reports = tmp_path / "stealth_reports"
    reports.mkdir()
    monkeypatch.setattr(_app_module, "_STEALTH_REPORTS_DIR", reports)

    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    with TestClient(app) as c:
        yield c, tmp_db, reports
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)


@pytest.fixture
def auth_headers():
    from bridge.config import get_settings

    return {"Authorization": f"Bearer {get_settings().bridge_auth_token}"}


def _seed_run(db_path, run_id="sr-test0001", status="success"):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO stealth_runs (run_id, created_at, url, query, source, status, "
            "http_status, html_len, items_count, items_json, duration_ms, agent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, "2026-06-12T10:00:00+00:00", "https://www.vinted.fr/x", "wacom",
             "vinted", status, 200, 9000, 2, '[{"title":"a"}]', 41000, "test"),
        )
        conn.commit()
    finally:
        conn.close()


_FAKE_RESULT = {
    "run_id": "sr-deadbeef",
    "status": "success",
    "security": {"waf": "Cloudflare", "captcha": False, "difficulty": 2},
    "result": {"http_status": 200, "html_len": 9000, "items_count": 3, "duration_ms": 50},
    "report": {"json_url": "/x.json", "csv_url": "/x.csv"},
}


class _FakeAgent:
    def __init__(self, settings, db_path):
        pass

    def run(self, url, query=None, source="custom", config=None, agent_id="manual"):
        return dict(_FAKE_RESULT)


def test_post_run_requires_auth(client):
    c, _, _ = client
    r = c.post("/stealth/run", json={"url": "https://x.com"})
    assert r.status_code == 401


def test_post_run_invalid_body_422(client, auth_headers):
    c, _, _ = client
    r = c.post("/stealth/run", json={"query": "no url"}, headers=auth_headers)
    assert r.status_code == 422


def test_post_run_mocked_agent_200(client, auth_headers, monkeypatch):
    import bridge.app as _app_module

    c, _, _ = client
    monkeypatch.setattr(_app_module, "StealthAgent", _FakeAgent)
    r = c.post(
        "/stealth/run",
        json={"url": "https://www.vinted.fr/x", "source": "vinted"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "sr-deadbeef"
    assert body["result"]["items_count"] == 3


def test_get_runs_list(client, auth_headers):
    c, db, _ = client
    _seed_run(db)
    r = c.get("/stealth/runs", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["runs"]) == 1
    assert body["runs"][0]["run_id"] == "sr-test0001"


def test_get_run_detail_200(client, auth_headers):
    c, db, _ = client
    _seed_run(db)
    r = c.get("/stealth/runs/sr-test0001", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "sr-test0001"
    assert body["items"] == [{"title": "a"}]


def test_get_run_detail_404(client, auth_headers):
    c, _, _ = client
    r = c.get("/stealth/runs/sr-missing", headers=auth_headers)
    assert r.status_code == 404


def test_get_report_csv_200(client, auth_headers):
    c, db, reports = client
    _seed_run(db)
    run_dir = reports / "sr-test0001"
    run_dir.mkdir()
    (run_dir / "report.csv").write_text("title,price_eur\na,10\n", encoding="utf-8")
    r = c.get("/stealth/runs/sr-test0001/report.csv", headers=auth_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


def test_get_status_200(client, auth_headers):
    c, db, _ = client
    _seed_run(db)
    r = c.get("/stealth/status/sr-test0001", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "sr-test0001"
    assert body["status"] == "success"


def test_report_path_traversal_blocked(client, auth_headers):
    c, _, reports = client
    # secret lives OUTSIDE the reports dir; traversal must not reach it
    (reports.parent / "secret.csv").write_text("leak", encoding="utf-8")
    r = c.get("/stealth/runs/..%2f..%2fsecret/report.csv", headers=auth_headers)
    assert r.status_code == 404
