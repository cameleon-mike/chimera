"""Tests for network.fingerprints.loader.FingerprintLoader.

All fixtures are inline (tmp_path) — no dependency on real JSON files.
"""
from __future__ import annotations

import json

import pytest

from network.fingerprints.loader import FingerprintLoader

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


def test_pick_coherent_no_geo_returns_all_fields(fp_dir):
    loader = FingerprintLoader(fingerprints_dir=fp_dir)
    fp = loader.pick_coherent()
    required_keys = {"profile_id", "ua", "headers", "header_order", "viewport", "locale", "timezone", "proxy_country"}
    assert required_keys.issubset(fp.keys())
    assert isinstance(fp["profile_id"], str)
    assert isinstance(fp["ua"], str)
    assert isinstance(fp["headers"], dict)
    assert isinstance(fp["header_order"], list)
    assert isinstance(fp["viewport"], list)
    assert len(fp["viewport"]) == 2


def test_pick_coherent_with_geo_id_uses_compatible_profile(fp_dir):
    loader = FingerprintLoader(fingerprints_dir=fp_dir)
    fp = loader.pick_coherent(geo_id="fr-paris")
    assert fp["profile_id"] in MINIMAL_GEO["fr-paris"]["compatible_ua_profiles"]
    assert fp["locale"] == "fr-FR"
    assert fp["timezone"] == "Europe/Paris"
    assert fp["proxy_country"] == "FR"


def test_pick_coherent_unknown_geo_falls_back_to_random(fp_dir):
    loader = FingerprintLoader(fingerprints_dir=fp_dir)
    # Must not raise even for a non-existent geo_id
    fp = loader.pick_coherent(geo_id="geo-inexistant")
    assert "profile_id" in fp
    assert fp["locale"] is None
    assert fp["timezone"] is None
    assert fp["proxy_country"] is None


def test_get_profile_known_returns_profile(fp_dir):
    loader = FingerprintLoader(fingerprints_dir=fp_dir)
    p = loader.get_profile("chrome127-win")
    assert p is not None
    assert p["id"] == "chrome127-win"


def test_get_profile_unknown_returns_none(fp_dir):
    loader = FingerprintLoader(fingerprints_dir=fp_dir)
    assert loader.get_profile("nonexistent-profile") is None


def test_validate_pool_valid_pool_returns_empty(fp_dir):
    loader = FingerprintLoader(fingerprints_dir=fp_dir)
    errors = loader.validate_pool()
    assert errors == [], f"Expected no errors, got: {errors}"
