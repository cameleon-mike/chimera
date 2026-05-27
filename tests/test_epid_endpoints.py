"""Tests for ePID endpoints in bridge/app.py — 12 tests."""

from __future__ import annotations

import sqlite3
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """TestClient with isolated SQLite DB and no dependency_overrides leaking from other test files."""
    import bridge.app as _app_module
    from bridge.app import app

    tmp_db = tmp_path / "risk_db.sqlite"
    original_path = _app_module._RISK_DB_PATH
    _app_module._RISK_DB_PATH = tmp_db
    _app_module._init_risk_db()

    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    with TestClient(app) as c:
        yield c, tmp_db
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)
    _app_module._RISK_DB_PATH = original_path


@pytest.fixture
def auth_headers():
    from bridge.config import get_settings
    token = get_settings().bridge_auth_token
    return {"Authorization": f"Bearer {token}"}


# Helper

def _seed_epid(db_path: Path, epid: str):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO epid_stats
           (epid, brand, model, total_items, currency, median_price,
            q1_price, q2_price, q3_price, q4_price,
            avg_sell_days, min_sell_days, max_sell_days, sell_days_sample, last_updated)
        VALUES (?, 'Wacom', 'Cintiq 16', 5, 'EUR', 250.0,
                180.0, 220.0, 280.0, 350.0,
                12.4, 2.0, 45.0, 3, '2026-01-01T00:00:00')
        """,
        (epid,),
    )
    conn.commit()
    conn.close()


# --- GET /epid/stats/{epid} ---

def test_get_epid_stats_200(client, auth_headers):
    c, db = client
    _seed_epid(db, "EP123")
    r = c.get("/epid/stats/EP123", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["epid"] == "EP123"
    assert d["brand"] == "Wacom"
    assert d["median_price"] == 250.0
    assert d["avg_sell_days"] == 12.4

def test_get_epid_stats_404(client, auth_headers):
    c, _ = client
    r = c.get("/epid/stats/UNKNOWN_EPID", headers=auth_headers)
    assert r.status_code == 404

def test_get_epid_stats_no_auth(client):
    c, db = client
    _seed_epid(db, "EP999")
    r = c.get("/epid/stats/EP999")
    assert r.status_code == 401


# --- POST /epid/ingest ---

_SAMPLE_ITEMS = [
    {
        "epid": "EP001", "title": "Wacom Cintiq 16",
        "price_value": 250.0, "price_currency": "EUR",
        "start_date": None, "end_date": None,
        "source": "ebay", "url": "https://ebay.fr/itm/001",
    },
    {
        "epid": "EP001", "title": "Wacom Cintiq 16",
        "price_value": 300.0, "price_currency": "EUR",
        "start_date": None, "end_date": None,
        "source": "ebay", "url": "https://ebay.fr/itm/002",
    },
]

def test_ingest_basic(client, auth_headers):
    c, _ = client
    r = c.post("/epid/ingest", json={"items": _SAMPLE_ITEMS, "source": "ebay"}, headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["ingested"] == 2
    assert d["epids_updated"] >= 1

def test_ingest_no_duplicates(client, auth_headers):
    c, _ = client
    c.post("/epid/ingest", json={"items": _SAMPLE_ITEMS, "source": "ebay"}, headers=auth_headers)
    r2 = c.post("/epid/ingest", json={"items": _SAMPLE_ITEMS, "source": "ebay"}, headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["ingested"] == 0  # all duplicates by URL

def test_ingest_items_without_url_skipped(client, auth_headers):
    c, _ = client
    items = [{"epid": "EP001", "title": "X", "price_value": 100.0,
               "price_currency": "EUR", "url": None}]
    r = c.post("/epid/ingest", json={"items": items, "source": "test"}, headers=auth_headers)
    assert r.json()["ingested"] == 0

def test_ingest_then_search(client, auth_headers):
    c, _ = client
    c.post("/epid/ingest", json={"items": _SAMPLE_ITEMS, "source": "ebay"}, headers=auth_headers)
    r = c.get("/epid/search?q=Wacom", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert data[0]["brand"] == "Wacom"


# --- GET /epid/search ---

def test_search_returns_matches(client, auth_headers):
    c, db = client
    _seed_epid(db, "EPWACOM")
    r = c.get("/epid/search?q=Wacom", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert any(d["epid"] == "EPWACOM" for d in data)

def test_search_no_match_returns_empty(client, auth_headers):
    c, _ = client
    r = c.get("/epid/search?q=zzznomatch999", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []

def test_search_no_auth(client):
    c, _ = client
    r = c.get("/epid/search?q=wacom")
    assert r.status_code == 401


# --- ingest=true in /ebay/search (side-effect test) ---

def test_ebay_search_ingest_flag_accepted(client, auth_headers):
    """ingest=true param should not break /ebay/search (503 if no eBay keys configured)."""
    c, _ = client
    r = c.get("/ebay/search?q=wacom&ingest=true", headers=auth_headers)
    # Without eBay keys → 503 expected, not a 422/500 about unknown param
    assert r.status_code in (200, 503, 504)
