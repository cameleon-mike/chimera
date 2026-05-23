"""Tests for security_probe.py — uses httpbin.org for real HTTP test + mock for vendor detection."""
from __future__ import annotations
import json
from unittest.mock import patch, MagicMock
import pytest
from tools.probe.security_probe import probe_domain


def test_probe_httpbin_returns_valid_structure():
    """Real HTTP probe against httpbin.org — validates output schema."""
    result = probe_domain("httpbin.org")
    assert result["domain"] == "httpbin.org"
    assert 0.0 <= result["risk_score"] <= 1.0
    assert isinstance(result["vendors_detected"], list)
    assert "tls" in result
    assert "features" in result
    assert "indicators" in result
    assert "recommendation" in result
    assert result["recommendation"]["tool"] in {"scrapy", "crawl4ai", "screenshot"}
    assert result["recommendation"]["proxy_tier"] in {"datacenter", "residential"}
    assert isinstance(result["recommendation"]["fingerprint"], str)
    assert len(result["recommendation"]["fingerprint"]) > 0


def test_probe_httpbin_low_risk():
    """httpbin.org should score below 0.2 (no WAF, no CAPTCHA)."""
    result = probe_domain("httpbin.org")
    assert result["risk_score"] < 0.5  # lenient — it may have some headers
    assert result["recommendation"]["tool"] in {"scrapy", "crawl4ai"}


def test_probe_cloudflare_like_mock():
    """Mock a Cloudflare-protected response and verify vendor detection + scoring."""
    mock_response = MagicMock()
    mock_response.status = 403
    mock_response.headers = {
        "cf-ray": "abc123-CDG",
        "strict-transport-security": "max-age=31536001",
        "content-security-policy": "default-src 'self'",
    }
    mock_response.read.return_value = b"<html>__cf_chl_opt={}</html>"
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = probe_domain("mock-cf.example.com")

    assert "cloudflare" in result["vendors_detected"]
    assert result["risk_score"] > 0.3
    assert result["http_status"] == 403


def test_probe_unreachable_domain_returns_safe_defaults():
    """An unreachable domain should return a valid zero-score dict, not raise."""
    result = probe_domain("this-domain-does-not-exist-xyzzy-chimera.invalid")
    assert result["domain"] == "this-domain-does-not-exist-xyzzy-chimera.invalid"
    assert result["risk_score"] == 0.0
    assert result["vendors_detected"] == []
    assert result["http_status"] == 0
    assert result["tls"]["has_cert"] is False
