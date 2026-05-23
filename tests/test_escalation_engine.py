"""Tests for _compute_escalation — bridge-side escalation engine.

Tests the helper that queries risk_events and returns escalation hints.
Uses a temporary SQLite DB patched over bridge.app._RISK_DB_PATH.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.app import _compute_escalation

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
def mock_db(tmp_path):
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
            (job_id, "example.com", "https://example.com/", "2026-05-23T00:00:00Z",
             200, score, json.dumps(vendors), "{}", 5000, 100),
        )
    conn.commit()
    conn.close()


def test_no_risk_data_returns_not_needed(mock_db):
    result = _compute_escalation("unknown_job")
    assert result["needed"] is False
    assert result["reason"] == "no_risk_data"
    assert result["suggested_tool"] is None
    assert result["response_count"] == 0
    assert result["vendors_detected"] == []


def test_max_risk_one_triggers_screenshot(mock_db):
    _insert(mock_db, "job_max1", [(1.0, [])])
    result = _compute_escalation("job_max1")
    assert result["needed"] is True
    assert result["suggested_tool"] == "screenshot"


def test_avg_risk_0_8_suggests_screenshot(mock_db):
    _insert(mock_db, "job_avg08", [(0.8, []), (0.8, [])])
    result = _compute_escalation("job_avg08")
    assert result["needed"] is True
    assert result["suggested_tool"] == "screenshot"


def test_avg_risk_0_6_suggests_crawl4ai(mock_db):
    _insert(mock_db, "job_avg06", [(0.6, []), (0.6, [])])
    result = _compute_escalation("job_avg06")
    assert result["needed"] is True
    assert result["suggested_tool"] == "crawl4ai"


def test_low_risk_not_needed(mock_db):
    _insert(mock_db, "job_low", [(0.1, []), (0.2, []), (0.15, [])])
    result = _compute_escalation("job_low")
    assert result["needed"] is False
    assert result["suggested_tool"] is None


def test_pct_trigger_two_thirds_high_risk(mock_db):
    # 2 out of 3 responses are >= 0.5 → 66% >= 50% → trigger
    _insert(mock_db, "job_pct", [(0.6, []), (0.7, []), (0.1, [])])
    result = _compute_escalation("job_pct")
    assert result["needed"] is True
    assert result["suggested_tool"] is not None


def test_pct_trigger_low_avg_still_has_suggested_tool(mock_db):
    # pct_trigger with avg < 0.5 — needed=True must imply suggested_tool non-null
    _insert(mock_db, "job_pct_low", [(0.5, []), (0.5, []), (0.1, [])])
    result = _compute_escalation("job_pct_low")
    assert result["needed"] is True
    assert result["suggested_tool"] is not None


def test_vendors_aggregated_and_sorted(mock_db):
    _insert(mock_db, "job_v", [(0.7, ["cloudflare"]), (0.6, ["akamai", "cloudflare"])])
    result = _compute_escalation("job_v")
    assert result["vendors_detected"] == ["akamai", "cloudflare"]


def test_trigger_threshold_always_0_5(mock_db):
    result = _compute_escalation("any_job_x")
    assert result["trigger_threshold"] == pytest.approx(0.5)
