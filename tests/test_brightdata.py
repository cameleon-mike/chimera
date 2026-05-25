"""Tests for Bright Data proxy URL builder."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_settings(username="brd-customer-test-zone-abc", password="testpass",
                   host="brd.superproxy.io", port=33335):
    s = MagicMock()
    s.brightdata_username = username
    s.brightdata_password = password
    s.brightdata_host = host
    s.brightdata_port = port
    return s


def test_build_proxy_url_with_country():
    from network.proxy_pool.brightdata import build_proxy_url
    with patch("network.proxy_pool.brightdata.get_settings", return_value=_mock_settings()):
        url = build_proxy_url("BE", "residential")
    assert url is not None
    assert "country-be" in url
    assert "brd.superproxy.io:33335" in url


def test_build_proxy_url_without_country():
    from network.proxy_pool.brightdata import build_proxy_url
    with patch("network.proxy_pool.brightdata.get_settings", return_value=_mock_settings()):
        url = build_proxy_url()
    assert url is not None
    assert "country" not in url
    assert "brd-customer-test-zone-abc" in url


def test_build_proxy_url_no_credentials_returns_none():
    from network.proxy_pool.brightdata import build_proxy_url
    with patch("network.proxy_pool.brightdata.get_settings",
               return_value=_mock_settings(username="", password="")):
        url = build_proxy_url("BE")
    assert url is None


def test_build_proxy_url_no_username_returns_none():
    from network.proxy_pool.brightdata import build_proxy_url
    with patch("network.proxy_pool.brightdata.get_settings",
               return_value=_mock_settings(username="")):
        url = build_proxy_url("FR")
    assert url is None


def test_country_suffix_is_lowercase():
    from network.proxy_pool.brightdata import build_proxy_url
    with patch("network.proxy_pool.brightdata.get_settings", return_value=_mock_settings()):
        url = build_proxy_url("FR")
    assert "country-fr" in url
    assert "country-FR" not in url


def test_get_proxy_for_profile_returns_server_dict():
    from network.proxy_pool.brightdata import get_proxy_for_profile
    with patch("network.proxy_pool.brightdata.get_settings", return_value=_mock_settings()):
        proxy = get_proxy_for_profile("DE")
    assert proxy is not None
    assert "server" in proxy
    assert "country-de" in proxy["server"]


def test_get_proxy_for_profile_no_creds_returns_none():
    from network.proxy_pool.brightdata import get_proxy_for_profile
    with patch("network.proxy_pool.brightdata.get_settings",
               return_value=_mock_settings(username="")):
        proxy = get_proxy_for_profile("BE")
    assert proxy is None


def test_password_not_in_url_when_no_creds():
    """Verify no accidental plaintext password when credentials are empty."""
    from network.proxy_pool.brightdata import build_proxy_url
    with patch("network.proxy_pool.brightdata.get_settings",
               return_value=_mock_settings(username="", password="secret")):
        url = build_proxy_url("BE")
    assert url is None  # returns None before constructing URL — password never exposed
