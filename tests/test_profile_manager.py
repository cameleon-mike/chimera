"""Tests for ProfileManager — no real browser (Playwright is mocked)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.screenshot_runner.profile_manager import ProfileManager


@pytest.fixture
def pm(tmp_path: Path):
    return ProfileManager(profiles_dir=tmp_path / "cookies")


# --- register_profile -------------------------------------------------------

def test_register_profile_creates_entry(pm):
    pm.register_profile("prof-be", {"proxy_country": "BE", "geo_id": "be-brussels"})
    assert "prof-be" in pm.meta
    p = pm.meta["prof-be"]
    assert p["proxy_country"] == "BE"
    assert p["geo_id"] == "be-brussels"
    assert p["status"] == "created"
    assert p["warmed"] is False
    assert p["age_days"] == 0


def test_register_profile_defaults(pm):
    pm.register_profile("p1", {})
    p = pm.meta["p1"]
    assert p["proxy_country"] == "FR"
    assert p["geo_id"] == "fr-paris"


def test_meta_persisted_to_disk(pm):
    pm.register_profile("p1", {"proxy_country": "NL"})
    pm2 = ProfileManager(profiles_dir=pm.profiles_dir)
    assert "p1" in pm2.meta
    assert pm2.meta["p1"]["proxy_country"] == "NL"


# --- list_profiles -----------------------------------------------------------

def test_list_profiles_empty(pm):
    assert pm.list_profiles() == []


def test_list_profiles_after_register(pm):
    pm.register_profile("p1", {})
    pm.register_profile("p2", {"proxy_country": "DE"})
    assert len(pm.list_profiles()) == 2


# --- get_ready_profiles ------------------------------------------------------

def test_get_ready_profiles_excludes_unwarmed(pm):
    pm.register_profile("p1", {})
    assert pm.get_ready_profiles(min_age_days=0) == []


def test_get_ready_profiles_includes_warmed(pm):
    pm.register_profile("p1", {})
    pm.meta["p1"]["warmed"] = True
    pm.meta["p1"]["age_days"] = 0
    pm._save_meta()
    assert len(pm.get_ready_profiles(min_age_days=0)) == 1


def test_get_ready_profiles_min_age_filter(pm):
    pm.register_profile("young", {})
    pm.register_profile("old", {})
    pm.meta["young"]["warmed"] = True
    pm.meta["young"]["age_days"] = 0
    pm.meta["old"]["warmed"] = True
    pm.meta["old"]["age_days"] = 3
    pm._save_meta()
    assert len(pm.get_ready_profiles(min_age_days=1)) == 1
    assert pm.get_ready_profiles(min_age_days=1)[0]["profile_id"] == "old"


# --- get_best_profile_for_domain ---------------------------------------------

def test_get_best_profile_no_profiles(pm):
    assert pm.get_best_profile_for_domain("ebay.de") is None


def test_get_best_profile_geo_match_de(pm):
    pm.register_profile("de", {"proxy_country": "DE"})
    pm.register_profile("fr", {"proxy_country": "FR"})
    pm.meta["de"]["warmed"] = True
    pm.meta["fr"]["warmed"] = True
    pm._save_meta()
    result = pm.get_best_profile_for_domain("ebay.de")
    assert result is not None
    assert result["proxy_country"] == "DE"


def test_get_best_profile_geo_match_fr(pm):
    pm.register_profile("de", {"proxy_country": "DE"})
    pm.register_profile("fr", {"proxy_country": "FR"})
    pm.meta["de"]["warmed"] = True
    pm.meta["fr"]["warmed"] = True
    pm._save_meta()
    result = pm.get_best_profile_for_domain("leboncoin.fr")
    assert result is not None
    assert result["proxy_country"] == "FR"


def test_get_best_profile_prefers_highest_age(pm):
    pm.register_profile("new-de", {"proxy_country": "DE"})
    pm.register_profile("old-de", {"proxy_country": "DE"})
    pm.meta["new-de"]["warmed"] = True
    pm.meta["new-de"]["age_days"] = 1
    pm.meta["old-de"]["warmed"] = True
    pm.meta["old-de"]["age_days"] = 10
    pm._save_meta()
    result = pm.get_best_profile_for_domain("ebay.de")
    assert result["profile_id"] == "old-de"


def test_get_best_profile_none_warmed(pm):
    pm.register_profile("de", {"proxy_country": "DE"})
    assert pm.get_best_profile_for_domain("ebay.de") is None


# --- micro_session -----------------------------------------------------------

async def test_micro_session_increments_age_days(pm):
    pm.register_profile("p1", {"proxy_country": "FR"})
    pm.meta["p1"]["warmed"] = True
    pm._save_meta()

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.close = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.add_init_script = AsyncMock()
    mock_ctx.new_page = AsyncMock(return_value=mock_page)
    mock_ctx.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_ctx)

    mock_playwright = MagicMock()
    mock_playwright.chromium = mock_chromium

    mock_pw_cm = MagicMock()
    mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.screenshot_runner.profile_manager.async_playwright",
               return_value=mock_pw_cm), \
         patch("tools.screenshot_runner.profile_manager.get_proxy_for_profile",
               return_value=None):
        result = await pm.micro_session("p1")

    assert pm.meta["p1"]["age_days"] == 1
    assert "sites_visited" in result
    assert result["profile_id"] == "p1"
