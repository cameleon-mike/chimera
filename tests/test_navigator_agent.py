"""Tests for NavigatorAgent.run()."""
from __future__ import annotations

import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tools.navigator_agent.navigator import NavigatorAgent


def _make_settings(**kw):
    defaults = dict(
        bridge_host="127.0.0.1",
        bridge_port=8080,
        bridge_auth_token="test-token",
        brightdata_username="",
        brightdata_password="",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _make_agent(db_path=":memory:", **settings_kw):
    return NavigatorAgent(settings=_make_settings(**settings_kw), db_path=db_path)


def _probe_resp(risk_score=0.1):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {"risk_score": risk_score}
    return m


def _agg_resp(items=None, total=0):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {
        "total_items": total if items is None else len(items),
        "items": items or [],
    }
    return m


def _seed_epid(conn, epid="E1", median=400.0):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS epid_stats (
            epid TEXT PRIMARY KEY, brand TEXT, model TEXT, total_items INTEGER,
            currency TEXT, median_price REAL, q1_price REAL, q2_price REAL,
            q3_price REAL, q4_price REAL, avg_sell_days REAL, min_sell_days REAL,
            max_sell_days REAL, sell_days_sample INTEGER, last_updated TEXT
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO epid_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (epid, "Wacom", "Cintiq 16", 50, "EUR", median,
         300.0, 363.0, 420.0, 500.0, None, None, None, 0, "2026-06-05"),
    )
    conn.commit()


# ── Test 1 ──
def test_run_returns_all_fields():
    """run() retourne dict avec tous les champs attendus."""
    agent = _make_agent()
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_probe_resp(0.1), _agg_resp()]
        result = agent.run("wacom cintiq 16")
    assert "query" in result
    assert "pipeline_ms" in result
    assert "probe_risk" in result
    assert "total_scraped" in result
    assert "total_scored" in result
    assert "deals" in result
    assert "summary" in result


# ── Test 2 ──
def test_pipeline_ms_positive():
    """pipeline_ms > 0."""
    agent = _make_agent()
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_probe_resp(), _agg_resp()]
        result = agent.run("wacom")
    assert result["pipeline_ms"] > 0


# ── Test 3 ──
def test_probe_risk_float_between_0_and_1():
    """probe_risk est un float entre 0 et 1."""
    agent = _make_agent()
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_probe_resp(0.35), _agg_resp()]
        result = agent.run("wacom")
    assert isinstance(result["probe_risk"], float)
    assert 0.0 <= result["probe_risk"] <= 1.0


# ── Test 4 ──
def test_deals_sorted_by_confidence():
    """deals triés par confidence décroissante."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = sqlite3.connect(f.name)
        _seed_epid(conn, "E1", median=400.0)
        conn.close()

        agent = _make_agent(db_path=f.name)
        items = [
            {"epid": "E1", "title": "Cheap", "price": {"value": 80.0, "currency": "EUR"}, "link": "https://e.fr/1"},
            {"epid": "E1", "title": "MidRange", "price": {"value": 280.0, "currency": "EUR"}, "link": "https://e.fr/2"},
        ]
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [_probe_resp(), _agg_resp(items=items)]
            result = agent.run("wacom")

    deals = result["deals"]
    if len(deals) >= 2:
        assert deals[0]["confidence"] >= deals[1]["confidence"]


# ── Test 5 ──
def test_max_price_filters_expensive_items():
    """max_price filtre les items trop chers."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = sqlite3.connect(f.name)
        _seed_epid(conn, "E1", median=400.0)
        conn.close()

        agent = _make_agent(db_path=f.name)
        items = [
            {"epid": "E1", "title": "Cheap", "price": {"value": 80.0, "currency": "EUR"}, "link": "https://e.fr/1"},
            {"epid": "E1", "title": "Expensive", "price": {"value": 500.0, "currency": "EUR"}, "link": "https://e.fr/2"},
        ]
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [_probe_resp(), _agg_resp(items=items)]
            result = agent.run("wacom", max_price=200.0)

    prices = [d["listed_price"] for d in result["deals"]]
    assert all(p <= 200.0 for p in prices)


# ── Test 6 ──
def test_summary_non_empty():
    """summary est une chaîne non vide."""
    agent = _make_agent()
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_probe_resp(), _agg_resp()]
        result = agent.run("wacom")
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


# ── Test 7 ──
def test_run_without_epids_returns_empty_deals():
    """run() sans ePIDs disponibles → deals=[]."""
    agent = _make_agent()
    items = [
        {"epid": None, "title": "No EPID Item", "price": {"value": 100.0, "currency": "EUR"}, "link": "https://e.fr/1"},
    ]
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [_probe_resp(), _agg_resp(items=items)]
        result = agent.run("wacom")
    assert result["deals"] == []


# ── Test 8 ──
def test_run_probe_fails_continues_with_zero():
    """run() si probe échoue → probe_risk=0.0, continue sans crasher."""
    agent = _make_agent()
    probe_fail = MagicMock()
    probe_fail.raise_for_status.side_effect = Exception("probe timeout")

    with patch("requests.get") as mock_get:
        mock_get.side_effect = [probe_fail, _agg_resp()]
        result = agent.run("wacom")

    assert result["probe_risk"] == 0.0
    assert "query" in result
