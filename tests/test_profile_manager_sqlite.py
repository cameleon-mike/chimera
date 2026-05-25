"""Tests ProfileManager SQLite backend — vérifie la couche de persistance."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.screenshot_runner.profile_manager import ProfileManager


@pytest.fixture
def pm(tmp_path: Path) -> ProfileManager:
    return ProfileManager(profiles_dir=tmp_path / "cookies")


def test_register_profile_writes_sqlite(pm):
    """register_profile() écrit dans SQLite (pas seulement en mémoire)."""
    pm.register_profile("p-sq-001", {"proxy_country": "BE", "geo_id": "be-brussels"})

    conn = sqlite3.connect(str(pm._db_path))
    row = conn.execute(
        "SELECT profile_id, proxy_country FROM profiles WHERE profile_id=?", ("p-sq-001",)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[1] == "BE"


def test_list_profiles_reads_sqlite(pm):
    """list_profiles() retourne les profils depuis SQLite."""
    pm.register_profile("p1", {"proxy_country": "FR"})
    pm.register_profile("p2", {"proxy_country": "DE"})

    # Nouvel instance → doit lire depuis SQLite
    pm2 = ProfileManager(profiles_dir=pm.profiles_dir)
    result = pm2.list_profiles()

    ids = {p["profile_id"] for p in result}
    assert "p1" in ids
    assert "p2" in ids


def test_get_ready_profiles_filters_sqlite(pm):
    """get_ready_profiles() filtre depuis SQLite."""
    pm.register_profile("ready-p", {"proxy_country": "NL"})
    pm.meta["ready-p"]["warmed"] = True
    pm.meta["ready-p"]["age_days"] = 5
    pm._save_meta()

    pm.register_profile("unwarmed-p", {"proxy_country": "GB"})
    # unwarmed-p: warmed=False, ne doit pas apparaître

    ready = pm.get_ready_profiles(min_age_days=1)
    ids = [p["profile_id"] for p in ready]
    assert "ready-p" in ids
    assert "unwarmed-p" not in ids


def test_update_profile_status_updates_sqlite(pm):
    """update_profile_status() met à jour SQLite."""
    pm.register_profile("p-status", {"proxy_country": "FR"})
    pm.update_profile_status("p-status", "warming")

    conn = sqlite3.connect(str(pm._db_path))
    row = conn.execute(
        "SELECT status FROM profiles WHERE profile_id=?", ("p-status",)
    ).fetchone()
    conn.close()
    assert row[0] == "warming"


@pytest.mark.asyncio
async def test_warm_up_compatible_with_sqlite_profile(pm):
    """Profil créé via SQLite → warm_up fonctionne sans erreur."""
    pm.register_profile("p-compat", {"proxy_country": "BE", "geo_id": "be-brussels"})

    mock_ctx = AsyncMock()
    mock_ctx.add_init_script = AsyncMock()
    mock_ctx.new_page = AsyncMock(return_value=AsyncMock(
        goto=AsyncMock(), wait_for_timeout=AsyncMock(),
        mouse=MagicMock(wheel=AsyncMock()), close=AsyncMock()
    ))
    mock_ctx.cookies = AsyncMock(return_value=[{"name": "c1", "value": "v1"}])
    mock_ctx.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_ctx)
    mock_playwright = MagicMock(chromium=mock_chromium)
    mock_pw_cm = MagicMock(
        __aenter__=AsyncMock(return_value=mock_playwright),
        __aexit__=AsyncMock(return_value=False),
    )

    with patch("tools.screenshot_runner.profile_manager.async_playwright", return_value=mock_pw_cm), \
         patch("tools.screenshot_runner.profile_manager.get_proxy_for_profile", return_value=None):
        result = await pm.warm_up("p-compat")

    assert result["profile_id"] == "p-compat"
    assert result["cookies_collected"] >= 1
