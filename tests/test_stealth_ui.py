"""Tests for the Stealth UI tab (S5)."""

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


def test_ui_contains_stealth(client):
    """Test that /ui includes STEALTH in the HTML."""
    c, _, _ = client
    r = c.get("/ui")
    assert r.status_code == 200
    assert "STEALTH" in r.text


def test_stealth_runs_list_ok(client, auth_headers):
    """Test that /stealth/runs returns a list."""
    c, db, _ = client
    _seed_run(db)
    r = c.get("/stealth/runs", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body


def test_stealth_run_detail_ok(client, auth_headers):
    """Test that /stealth/runs/{run_id} returns run detail."""
    c, db, _ = client
    _seed_run(db)
    r = c.get("/stealth/runs/sr-test0001", headers=auth_headers)
    assert r.status_code == 200


def test_stealth_report_csv_content_type(client, auth_headers):
    """Test that /stealth/runs/{run_id}/report.csv returns CSV content type."""
    c, db, reports = client
    _seed_run(db)
    run_dir = reports / "sr-test0001"
    run_dir.mkdir()
    (run_dir / "report.csv").write_text("title,price_eur\na,10\n", encoding="utf-8")
    r = c.get("/stealth/runs/sr-test0001/report.csv", headers=auth_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
