"""Tests for FingerprintLoader.validate_pool() coherence checks.

All fixtures are inline (tmp_path) — no dependency on real JSON files.
"""
from __future__ import annotations

import copy
import json

import pytest

from network.fingerprints.loader import FingerprintLoader

# ---------------------------------------------------------------------------
# Base minimal valid pool (shared across all tests)
# ---------------------------------------------------------------------------

BASE_UA = {
    "profiles": [{
        "id": "chrome127-win",
        "browser": "chrome",
        "browser_version": "127",
        "platform": "Windows",
        "platform_version": "10",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.72 Safari/537.36",
        "sec_ch_ua": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept_language": "en-US,en;q=0.9",
        "viewport_options": [[1920, 1080], [1536, 864]],
        "_captured_from": "test",
    }]
}
BASE_HEADERS = {
    "by_profile_id": {
        "chrome127-win": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "_order": ["Accept", "Accept-Encoding", "Accept-Language"],
        }
    }
}
BASE_GEO = {
    "fr-paris": {
        "timezone": "Europe/Paris",
        "locale": "fr-FR",
        "accept_language": "fr-FR,fr;q=0.9,en;q=0.8",
        "proxy_country": "FR",
        "compatible_ua_profiles": ["chrome127-win"],
    }
}


def _write_pool(tmp_path, ua=None, headers=None, geo=None):
    (tmp_path / "ua_pool.json").write_text(json.dumps(ua or BASE_UA))
    (tmp_path / "headers_pool.json").write_text(json.dumps(headers or BASE_HEADERS))
    (tmp_path / "geo_profiles.json").write_text(json.dumps(geo or BASE_GEO))
    return FingerprintLoader(fingerprints_dir=tmp_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chrome_profile_with_firefox_sec_ch_ua(tmp_path):
    ua = copy.deepcopy(BASE_UA)
    ua["profiles"][0]["sec_ch_ua"] = '"Firefox";v="125"'
    loader = _write_pool(tmp_path, ua=ua)
    errors = loader.validate_pool()
    assert any("Firefox" in e and "sec_ch_ua" in e for e in errors), errors


def test_viewport_width_below_320(tmp_path):
    ua = copy.deepcopy(BASE_UA)
    ua["profiles"][0]["viewport_options"] = [[100, 480]]
    loader = _write_pool(tmp_path, ua=ua)
    errors = loader.validate_pool()
    assert any("unrealistic viewport" in e for e in errors), errors


def test_order_lists_missing_header(tmp_path):
    headers = copy.deepcopy(BASE_HEADERS)
    headers["by_profile_id"]["chrome127-win"]["_order"].append("X-Missing-Header")
    loader = _write_pool(tmp_path, headers=headers)
    errors = loader.validate_pool()
    assert any("X-Missing-Header" in e and "_order" in e for e in errors), errors


def test_geo_references_unknown_profile(tmp_path):
    geo = copy.deepcopy(BASE_GEO)
    geo["fr-paris"]["compatible_ua_profiles"].append("nonexistent-profile")
    loader = _write_pool(tmp_path, geo=geo)
    errors = loader.validate_pool()
    assert any("nonexistent-profile" in e for e in errors), errors


def test_ua_contains_bot_signal_selenium(tmp_path):
    ua = copy.deepcopy(BASE_UA)
    ua["profiles"][0]["ua"] = "Mozilla/5.0 Selenium/4.0 compatible"
    loader = _write_pool(tmp_path, ua=ua)
    errors = loader.validate_pool()
    assert any("selenium" in e.lower() and "bot signal" in e for e in errors), errors


def test_valid_pool_returns_no_errors(tmp_path):
    loader = _write_pool(tmp_path)
    errors = loader.validate_pool()
    assert errors == [], f"Expected no errors, got: {errors}"
