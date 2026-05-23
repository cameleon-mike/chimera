"""Tests for RotateUAMiddleware (tools/scrapy_runner/project/middlewares/rotate_ua.py).

Uses tmp_path fixtures for JSON files and MagicMock for Scrapy objects.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

MINIMAL_UA = {
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
MINIMAL_HEADERS = {
    "by_profile_id": {
        "chrome127-win": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "_order": ["Accept", "Accept-Encoding", "Accept-Language"],
        }
    }
}
MINIMAL_GEO = {
    "fr-paris": {
        "timezone": "Europe/Paris",
        "locale": "fr-FR",
        "accept_language": "fr-FR,fr;q=0.9,en;q=0.8",
        "proxy_country": "FR",
        "compatible_ua_profiles": ["chrome127-win"],
    }
}


@pytest.fixture
def fp_dir(tmp_path):
    (tmp_path / "ua_pool.json").write_text(json.dumps(MINIMAL_UA))
    (tmp_path / "headers_pool.json").write_text(json.dumps(MINIMAL_HEADERS))
    (tmp_path / "geo_profiles.json").write_text(json.dumps(MINIMAL_GEO))
    return tmp_path


def _make_mock_request():
    """Return a MagicMock that mimics a Scrapy request with a real dict-like headers store."""
    request = MagicMock()
    # Use a real dict to track header assignments
    _headers_store = {}

    def _headers_clear():
        _headers_store.clear()

    def _headers_setitem(key, value):
        _headers_store[key] = value

    def _headers_getitem(key):
        return _headers_store[key]

    request.headers = MagicMock()
    request.headers.clear.side_effect = _headers_clear
    request.headers.__setitem__ = MagicMock(side_effect=_headers_setitem)
    request.headers.__getitem__ = MagicMock(side_effect=_headers_getitem)
    request.meta = {}
    request._headers_store = _headers_store  # expose for assertions
    return request


def test_process_request_sets_user_agent(fp_dir):
    from tools.scrapy_runner.project.middlewares.rotate_ua import RotateUAMiddleware

    mw = RotateUAMiddleware(fingerprints_dir=str(fp_dir), geo_id=None)
    request = _make_mock_request()
    spider = MagicMock()

    mw.process_request(request, spider)

    expected_ua = MINIMAL_UA["profiles"][0]["ua"]
    assert request._headers_store.get("User-Agent") == expected_ua


def test_process_request_sets_fingerprint_profile_meta(fp_dir):
    from tools.scrapy_runner.project.middlewares.rotate_ua import RotateUAMiddleware

    mw = RotateUAMiddleware(fingerprints_dir=str(fp_dir), geo_id=None)
    request = _make_mock_request()
    spider = MagicMock()

    mw.process_request(request, spider)

    assert request.meta.get("fingerprint_profile") == "chrome127-win"


def test_process_request_applies_headers_in_order(fp_dir):
    from tools.scrapy_runner.project.middlewares.rotate_ua import RotateUAMiddleware

    mw = RotateUAMiddleware(fingerprints_dir=str(fp_dir), geo_id=None)
    request = _make_mock_request()
    spider = MagicMock()

    call_order = []

    def _track_setitem(key, value):
        call_order.append(key)
        request._headers_store[key] = value

    request.headers.__setitem__ = MagicMock(side_effect=_track_setitem)

    mw.process_request(request, spider)

    expected_order = ["Accept", "Accept-Encoding", "Accept-Language"]
    # Only check the non-UA headers appear before User-Agent
    non_ua_calls = [k for k in call_order if k != "User-Agent"]
    assert non_ua_calls == expected_order, f"Header order mismatch: {non_ua_calls}"
    # User-Agent is last
    assert call_order[-1] == "User-Agent"


def test_from_crawler_reads_settings(fp_dir):
    from tools.scrapy_runner.project.middlewares.rotate_ua import RotateUAMiddleware

    crawler = MagicMock()
    crawler.settings.get.side_effect = lambda key, default=None: {
        "FINGERPRINTS_DIR": str(fp_dir),
        "GEO_ID": "fr-paris",
    }.get(key, default)
    crawler.settings.getint.side_effect = lambda key, default=None: default

    mw = RotateUAMiddleware.from_crawler(crawler)

    assert mw.geo_id == "fr-paris"
    assert mw.loader is not None
    # SESSION_REDIS_URL not set → session_mgr is None
    assert mw._session_mgr is None
    assert mw._session_id is None
    # Verify it can pick a coherent fingerprint with the configured geo
    fp = mw.loader.pick_coherent(geo_id=mw.geo_id)
    assert fp["profile_id"] == "chrome127-win"


def test_process_request_uses_session_manager(fp_dir):
    from tools.scrapy_runner.project.middlewares.rotate_ua import RotateUAMiddleware
    from tests.test_session_manager import _mock_redis, _make_loader
    from tools.common.session_manager import SessionManager

    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)

    mw = RotateUAMiddleware(
        fingerprints_dir=str(fp_dir),
        geo_id=None,
        session_id="sess-sticky",
        session_mgr=sm,
    )
    request1 = _make_mock_request()
    request2 = _make_mock_request()
    spider = MagicMock()

    mw.process_request(request1, spider)
    mw.process_request(request2, spider)

    # Both requests got the same fingerprint profile
    assert request1.meta["fingerprint_profile"] == request2.meta["fingerprint_profile"]
