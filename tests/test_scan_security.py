"""Tests for ScanSecurity (Stealth S1) + stealth_runs SQLite migration."""

from __future__ import annotations

import sqlite3

import pytest

from tools.camoufox_runner import scan_security as ss
from tools.camoufox_runner.scan_security import ScanSecurity


class _DummySettings:
    pass


@pytest.fixture
def scanner(monkeypatch):
    """ScanSecurity with private network methods stubbed to canned data."""
    s = ScanSecurity(_DummySettings())
    monkeypatch.setattr(
        s,
        "_caniscrape_scan",
        lambda url: {
            "tls": {"status": "active"},
            "captcha": {"captcha_detected": True},
            "score_card": {"score": 4},
        },
    )
    monkeypatch.setattr(s, "_wafw00f_scan", lambda url: {"waf_detected": "Cloudflare"})
    return s


def test_scan_returns_all_required_fields(scanner):
    result = scanner.scan("https://example.com")
    for field in (
        "url",
        "waf",
        "captcha",
        "tls_fingerprinting",
        "difficulty",
        "proxy_recommendation",
        "tool_recommendation",
        "raw_caniscrape",
        "raw_wafw00f",
        "scanned_at",
    ):
        assert field in result, f"missing field: {field}"


def test_waf_present_in_security_map(scanner):
    result = scanner.scan("https://example.com")
    assert result["waf"] == "Cloudflare"


def test_captcha_is_bool(scanner):
    result = scanner.scan("https://example.com")
    assert isinstance(result["captcha"], bool)
    assert result["captcha"] is True


def test_difficulty_in_range(scanner):
    result = scanner.scan("https://example.com")
    assert isinstance(result["difficulty"], int)
    assert 0 <= result["difficulty"] <= 10


def test_tool_recommendation_valid(scanner):
    result = scanner.scan("https://example.com")
    assert result["tool_recommendation"] in ("scrapy", "crawl4ai", "camoufox")


def test_proxy_recommendation_valid(scanner):
    result = scanner.scan("https://example.com")
    assert result["proxy_recommendation"] in ("residential", "datacenter", "none")


def test_difficulty_capped_at_10():
    s = ScanSecurity(_DummySettings())
    caniscrape = {
        "score_card": {"score": 10},
        "tls": {"status": "active"},
        "captcha": {"captcha_detected": True},
    }
    wafw00f = {"waf_detected": "DataDome"}
    assert s._calculate_difficulty(caniscrape, wafw00f) == 10


def test_recommend_tool_thresholds():
    s = ScanSecurity(_DummySettings())
    assert s._recommend_tool(0) == "scrapy"
    assert s._recommend_tool(3) == "scrapy"
    assert s._recommend_tool(4) == "crawl4ai"
    assert s._recommend_tool(6) == "crawl4ai"
    assert s._recommend_tool(7) == "camoufox"
    assert s._recommend_tool(10) == "camoufox"


def test_caniscrape_scan_returns_empty_on_exception(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(ss, "analyze_tls_fingerprint", _boom)
    monkeypatch.setattr(ss, "check_robots_txt", _boom)
    s = ScanSecurity(_DummySettings())
    assert s._caniscrape_scan("https://example.com") == {}


def test_wafw00f_scan_returns_empty_on_exception(monkeypatch):
    class _Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("wafw00f failed")

    monkeypatch.setattr(ss, "WAFW00F", _Boom)
    s = ScanSecurity(_DummySettings())
    assert s._wafw00f_scan("https://example.com") == {}


def test_stealth_runs_table_created():
    from bridge import app as bridge_app

    bridge_app._init_risk_db()
    conn = sqlite3.connect(str(bridge_app._RISK_DB_PATH))
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
    finally:
        conn.close()
    assert "stealth_runs" in tables
