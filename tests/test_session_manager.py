"""Tests for SessionManager — sticky fingerprint + proxy per session_id."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tools.common.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_redis() -> tuple[MagicMock, dict]:
    """Return (redis_mock, backing_store). setex writes into store; get reads from it."""
    store: dict = {}
    r = MagicMock()
    r.get = lambda key: store.get(key)
    r.setex = lambda key, ttl, val: store.__setitem__(key, val)
    return r, store


def _make_loader(profile_id: str = "chrome127-win") -> MagicMock:
    loader = MagicMock()
    loader.pick_coherent.return_value = {
        "profile_id": profile_id,
        "ua": "Mozilla/5.0 ...",
        "headers": {"Accept": "*/*"},
        "header_order": ["Accept"],
        "viewport": [1920, 1080],
        "locale": None,
        "timezone": None,
        "proxy_country": None,
    }
    return loader


def _make_rotator(proxy_url: str = "http://proxy.example.com:8080") -> MagicMock:
    rotator = MagicMock()
    rotator.pick.return_value = {"url": proxy_url}
    return rotator


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------

def test_fingerprint_created_on_first_call():
    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)
    loader = _make_loader("firefox105-mac")

    fp = sm.get_or_create_fingerprint("sess-1", loader)

    assert fp["profile_id"] == "firefox105-mac"
    loader.pick_coherent.assert_called_once()


def test_fingerprint_reused_on_second_call():
    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)
    loader = _make_loader("chrome127-win")

    fp1 = sm.get_or_create_fingerprint("sess-2", loader)
    fp2 = sm.get_or_create_fingerprint("sess-2", loader)

    assert fp1 == fp2
    # pick_coherent called only once — second call hits Redis
    assert loader.pick_coherent.call_count == 1


def test_different_session_ids_are_independent():
    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)
    loader_a = _make_loader("chrome127-win")
    loader_b = _make_loader("firefox105-mac")

    fp_a = sm.get_or_create_fingerprint("sess-A", loader_a)
    fp_b = sm.get_or_create_fingerprint("sess-B", loader_b)

    assert fp_a["profile_id"] != fp_b["profile_id"]


# ---------------------------------------------------------------------------
# Proxy tests
# ---------------------------------------------------------------------------

def test_proxy_created_on_first_call():
    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)
    rotator = _make_rotator("http://p1.example.com:9050")

    url = sm.get_or_create_proxy("sess-3", rotator, "example.com")

    assert url == "http://p1.example.com:9050"
    rotator.pick.assert_called_once_with("example.com")


def test_proxy_reused_on_second_call():
    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)
    rotator = _make_rotator("http://p2.example.com:9050")

    url1 = sm.get_or_create_proxy("sess-4", rotator, "example.com")
    url2 = sm.get_or_create_proxy("sess-4", rotator, "other.com")  # different host, same session

    assert url1 == url2  # sticky: same proxy regardless of host
    assert rotator.pick.call_count == 1


def test_proxy_none_when_rotator_returns_none():
    redis, _ = _mock_redis()
    sm = SessionManager(redis, ttl=300)
    rotator = MagicMock()
    rotator.pick.return_value = None

    url = sm.get_or_create_proxy("sess-5", rotator, "example.com")

    assert url is None
