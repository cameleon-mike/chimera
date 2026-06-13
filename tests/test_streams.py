"""Tests for GET /streams (Cameleon DataStreams) — 0.9.1. 6 tests."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    import bridge.app as _app_module
    from bridge.app import app

    tmp_db = tmp_path / "risk_db.sqlite"
    _app_module._RISK_DB_PATH = tmp_db
    _app_module._init_risk_db()

    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    with TestClient(app) as c:
        yield c, tmp_db
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)


@pytest.fixture
def auth_headers():
    from bridge.config import get_settings

    return {"Authorization": f"Bearer {get_settings().bridge_auth_token}"}


def _seed_item(db, source, title="Wacom Cintiq 16", price=80.0):
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO scraped_items (title, price_value, source, scraped_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (title, price, source),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_stealth(db, status="success", error_msg=None):
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO stealth_runs (run_id, created_at, url, source, status, error_msg) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?)",
            ("sr-" + status, "https://x", "stealth", status, error_msg),
        )
        conn.commit()
    finally:
        conn.close()


def test_streams_requires_auth(client):
    c, _ = client
    assert c.get("/streams").status_code == 401


def test_streams_returns_four_cards(client, auth_headers):
    c, db = client
    _seed_item(db, "ebay")
    r = c.get("/streams", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 4


def test_streams_card_mandatory_fields(client, auth_headers):
    c, db = client
    _seed_item(db, "ebay")
    data = c.get("/streams", headers=auth_headers).json()
    for card in data:
        for field in (
            "id", "name", "source", "type", "status", "total_count",
            "today_count", "rate_per_hour", "last_item_ago_s", "preview_items",
        ):
            assert field in card


def test_streams_status_enum(client, auth_headers):
    c, db = client
    _seed_item(db, "ebay")
    data = c.get("/streams", headers=auth_headers).json()
    for card in data:
        assert card["status"] in ("live", "idle", "stalled", "error")


def test_streams_stealth_error_has_reason(client, auth_headers):
    c, db = client
    _seed_stealth(db, status="error", error_msg="proxy failed")
    data = c.get("/streams", headers=auth_headers).json()
    stealth = next(card for card in data if card["source"] == "stealth")
    assert stealth["status"] == "error"
    assert stealth["reason"] is not None


def test_streams_today_count_non_negative(client, auth_headers):
    c, db = client
    _seed_item(db, "ebay")
    data = c.get("/streams", headers=auth_headers).json()
    for card in data:
        assert card["today_count"] >= 0
