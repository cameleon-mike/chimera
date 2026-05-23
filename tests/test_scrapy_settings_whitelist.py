"""Tests for TD-10: Scrapy settings whitelist in run_scrapy._build_settings."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from tools.scrapy_runner.run_scrapy import _build_settings, _SCRAPY_SETTINGS_WHITELIST


def test_whitelisted_key_is_applied():
    config = {"settings": {"DOWNLOAD_DELAY": 2.5}}
    settings = _build_settings(config)
    assert settings.getfloat("DOWNLOAD_DELAY") == pytest.approx(2.5)


def test_non_whitelisted_key_is_rejected():
    config = {"settings": {"ITEM_PIPELINES": {"evil.pipeline.Class": 100}}}
    settings = _build_settings(config)
    # Should not raise — but the key must not be set to the evil value
    val = settings.get("ITEM_PIPELINES")
    # Either None or the default from settings.py — not the injected dict
    assert val != {"evil.pipeline.Class": 100}


def test_extensions_rejected():
    config = {"settings": {"EXTENSIONS": {"scrapy.extensions.Evil": 500}}}
    settings = _build_settings(config)
    val = settings.get("EXTENSIONS")
    assert val != {"scrapy.extensions.Evil": 500}


def test_downloader_middlewares_rejected():
    config = {"settings": {"DOWNLOADER_MIDDLEWARES": {"evil.Middleware": 100}}}
    settings = _build_settings(config)
    val = settings.get("DOWNLOADER_MIDDLEWARES")
    assert val != {"evil.Middleware": 100}


def test_proxy_tier_whitelisted():
    config = {"settings": {"PROXY_TIER": "residential"}}
    settings = _build_settings(config)
    assert settings.get("PROXY_TIER") == "residential"


def test_whitelist_set_contains_expected_keys():
    expected = {
        "DOWNLOAD_DELAY", "CONCURRENT_REQUESTS", "CONCURRENT_REQUESTS_PER_DOMAIN",
        "AUTOTHROTTLE_TARGET_CONCURRENCY", "ROBOTSTXT_OBEY", "USER_AGENT",
        "DEFAULT_REQUEST_HEADERS", "RETRY_TIMES", "DOWNLOAD_TIMEOUT", "PROXY_TIER",
    }
    assert expected.issubset(_SCRAPY_SETTINGS_WHITELIST)
