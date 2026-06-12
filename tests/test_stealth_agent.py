"""Tests for StealthAgent orchestrator (Stealth S3). Network phases mocked."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tools.camoufox_runner.stealth_agent import StealthAgent


class _DummySettings:
    groq_api_key = ""
    brightdata_password = ""


_EPID_STATS_DDL = """
CREATE TABLE IF NOT EXISTS epid_stats (
    epid            TEXT PRIMARY KEY,
    brand           TEXT,
    model           TEXT,
    total_items     INTEGER DEFAULT 0,
    currency        TEXT,
    median_price    REAL,
    q1_price        REAL,
    q2_price        REAL,
    q3_price        REAL,
    q4_price        REAL,
    avg_sell_days   REAL,
    min_sell_days   REAL,
    max_sell_days   REAL,
    sell_days_sample INTEGER DEFAULT 0,
    last_updated    TEXT
);
"""


@pytest.fixture
def agent(tmp_path):
    db = str(tmp_path / "test.sqlite")
    a = StealthAgent(_DummySettings(), db)
    a.reports_dir = tmp_path / "reports"
    a._phase1_scan = lambda url: {"waf": "Cloudflare", "captcha": False, "difficulty": 4}
    a._phase3_fetch = lambda url, cfg: {
        "http_status": 200,
        "html": "<html><body>ok</body></html>",
        "html_len": 30,
        "markdown": "wacom intuos 50 EUR",
        "tool": "camoufox",
    }
    a._phase4_extract = lambda html, md, source: [
        {"title": "Wacom Intuos", "price_eur": 50.0, "url": "https://v/1"}
    ]
    return a


def test_run_returns_structured_dict(agent):
    r = agent.run("https://www.vinted.fr/x", query="wacom", source="vinted")
    for key in ("run_id", "status", "security", "result", "report"):
        assert key in r, f"missing key: {key}"
    assert set(r["security"]) >= {"waf", "captcha", "difficulty"}
    assert set(r["result"]) >= {"http_status", "html_len", "items_count", "duration_ms"}
    assert set(r["report"]) >= {"json_url", "csv_url"}


def test_run_id_format(agent):
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    assert r["run_id"].startswith("sr-")
    assert len(r["run_id"]) == 11  # "sr-" + 8 hex chars


def test_status_success_on_http_200(agent):
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    assert r["status"] == "success"


def test_status_error_on_fetch_failure(agent):
    agent._phase3_fetch = lambda url, cfg: {"error": "launch failed", "tool": "camoufox", "html_len": 0}
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    assert r["status"] == "error"


def test_stealth_runs_row_created(agent):
    r = agent.run("https://www.vinted.fr/x", source="vinted", agent_id="tester")
    conn = sqlite3.connect(agent.db_path)
    try:
        row = conn.execute(
            "SELECT run_id, url, agent_id FROM stealth_runs WHERE run_id = ?",
            (r["run_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == r["run_id"]
    assert row[2] == "tester"


def test_stealth_runs_row_updated_with_items_count(agent):
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    conn = sqlite3.connect(agent.db_path)
    try:
        row = conn.execute(
            "SELECT items_count, status FROM stealth_runs WHERE run_id = ?",
            (r["run_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 1
    assert row[1] == "success"


def test_csv_report_created(agent):
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    csv_path = r["report"]["csv_url"]
    assert csv_path is not None
    from pathlib import Path

    p = Path(csv_path)
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "title" in content and "price_eur" in content


def test_json_report_created(agent):
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    json_path = r["report"]["json_url"]
    assert json_path is not None
    from pathlib import Path

    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert data["run_id"] == r["run_id"]
    assert "items" in data


def test_score_items_enriches_with_decision(agent):
    # Seed epid_stats so scoring has market data.
    conn = sqlite3.connect(agent.db_path)
    try:
        conn.executescript(_EPID_STATS_DDL)
        conn.execute(
            "INSERT INTO epid_stats (epid, median_price, avg_sell_days, sell_days_sample) "
            "VALUES (?, ?, ?, ?)",
            ("EP123", 200.0, 10.0, 5),
        )
        conn.commit()
    finally:
        conn.close()

    items = [{"title": "Cheap deal", "price_eur": 50.0, "epid": "EP123", "url": "u"}]
    enriched = agent._score_items(items)
    assert "decision" in enriched[0]
    assert "confidence" in enriched[0]


def test_run_never_crashes_when_phase3_raises(agent):
    def _boom(url, cfg):
        raise RuntimeError("phase3 exploded")

    agent._phase3_fetch = _boom
    r = agent.run("https://www.vinted.fr/x", source="vinted")
    assert r["status"] == "error"
    # report still generated even on crash
    assert r["report"]["json_url"] is not None
    from pathlib import Path

    assert Path(r["report"]["json_url"]).exists()
