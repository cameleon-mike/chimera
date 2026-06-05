"""Tests for GET /flipmachine/score and /flipmachine/deals endpoints."""
from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

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


def _mock_epid_row():
    """Return a tuple matching the epid_stats SELECT column order."""
    return (
        "TEST_EPID", "Wacom", "Cintiq 16", 50, "EUR",
        400.0,  # median_price
        300.0, 363.0, 420.0, 500.0,  # q1-q4
        None, None, None, 0,  # avg_sell_days, min, max, sell_days_sample
        "2026-06-05T00:00:00",
    )


def _mock_conn(row=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = [row] if row else []
    conn.execute.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.close = MagicMock()
    return conn


# ── Test 1 ──
def test_score_without_token():
    saved = app.dependency_overrides.pop(require_bearer, None)
    try:
        resp = TestClient(app).get("/flipmachine/score?epid=TEST&price=150")
        assert resp.status_code == 401
    finally:
        if saved is not None:
            app.dependency_overrides[require_bearer] = saved


# ── Test 2 ──
def test_score_missing_epid_param(client):
    resp = client.get("/flipmachine/score?price=150")
    assert resp.status_code == 422


# ── Test 3 ──
def test_score_unknown_epid_returns_404(client):
    mock_conn = _mock_conn(row=None)
    with patch("bridge.app._get_epid_conn", return_value=mock_conn):
        resp = client.get("/flipmachine/score?epid=UNKNOWN&price=150", headers=HEADERS)
    assert resp.status_code == 404


# ── Test 4 ──
def test_score_valid_returns_200_with_fields(client):
    mock_conn = _mock_conn(row=_mock_epid_row())
    with patch("bridge.app._get_epid_conn", return_value=mock_conn):
        resp = client.get("/flipmachine/score?epid=TEST_EPID&price=150", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "decision" in data
    assert "confidence" in data
    assert "margin_eur" in data
    assert "reasoning" in data
    assert data["decision"] in ("BUY", "OFFER", "SKIP")


# ── Test 5 ──
def test_deals_without_token():
    saved = app.dependency_overrides.pop(require_bearer, None)
    try:
        resp = TestClient(app).get("/flipmachine/deals?q=wacom")
        assert resp.status_code == 401
    finally:
        if saved is not None:
            app.dependency_overrides[require_bearer] = saved


# ── Test 6 ──
def test_deals_valid_returns_200(client):
    mock_ebay = AsyncMock(return_value={
        "items": [
            {"title": "Wacom Cintiq 16", "price": {"value": 150.0, "currency": "EUR"},
             "epid": "TEST_EPID", "link": "https://ebay.fr/1", "start_date": None, "end_date": None, "photo_url": None},
        ]
    })
    mock_deux = AsyncMock(return_value={"items": [], "_meta": {"blocked": False}})
    mock_conn = _mock_conn(row=_mock_epid_row())

    with patch("bridge.aggregator.fetch_ebay_raw", mock_ebay), \
         patch("bridge.aggregator.fetch_2ememain_raw", mock_deux), \
         patch("bridge.app._get_epid_conn", return_value=mock_conn):
        resp = client.get("/flipmachine/deals?q=wacom+cintiq+16", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert "deals" in data
    assert "deals_found" in data
    assert "total_scored" in data


# ── Test 7 ──
def test_deals_sorted_by_confidence(client):
    mock_ebay = AsyncMock(return_value={
        "items": [
            {"title": "Cheap Wacom", "price": {"value": 100.0, "currency": "EUR"},
             "epid": "E1", "link": "https://e.fr/1", "start_date": None, "end_date": None, "photo_url": None},
            {"title": "Mid Wacom", "price": {"value": 280.0, "currency": "EUR"},
             "epid": "E1", "link": "https://e.fr/2", "start_date": None, "end_date": None, "photo_url": None},
        ]
    })
    mock_deux = AsyncMock(return_value={"items": [], "_meta": {"blocked": False}})
    mock_conn = _mock_conn(row=_mock_epid_row())

    with patch("bridge.aggregator.fetch_ebay_raw", mock_ebay), \
         patch("bridge.aggregator.fetch_2ememain_raw", mock_deux), \
         patch("bridge.app._get_epid_conn", return_value=mock_conn):
        resp = client.get("/flipmachine/deals?q=wacom", headers=HEADERS)

    assert resp.status_code == 200
    deals = resp.json()["deals"]
    if len(deals) >= 2:
        assert deals[0]["confidence"] >= deals[1]["confidence"]


# ── Test 8 ──
def test_deals_decision_values_valid(client):
    mock_ebay = AsyncMock(return_value={
        "items": [
            {"title": "Wacom", "price": {"value": 150.0, "currency": "EUR"},
             "epid": "TEST_EPID", "link": "https://e.fr/1", "start_date": None, "end_date": None, "photo_url": None},
        ]
    })
    mock_deux = AsyncMock(return_value={"items": [], "_meta": {"blocked": False}})
    mock_conn = _mock_conn(row=_mock_epid_row())

    with patch("bridge.aggregator.fetch_ebay_raw", mock_ebay), \
         patch("bridge.aggregator.fetch_2ememain_raw", mock_deux), \
         patch("bridge.app._get_epid_conn", return_value=mock_conn):
        resp = client.get("/flipmachine/deals?q=wacom", headers=HEADERS)

    assert resp.status_code == 200
    for deal in resp.json()["deals"]:
        assert deal["decision"] in ("BUY", "OFFER", "SKIP")
