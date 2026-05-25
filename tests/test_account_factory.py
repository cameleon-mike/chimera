"""Tests AccountFactory — SQLite lifecycle, transitions statut, endpoints bridge."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tools.account_factory.factory import AccountFactory, CREATING, WARMING, READY, SENIOR, RECYCLE
from tools.account_factory.profile_config import ProfileConfig


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def factory(tmp_path: Path) -> AccountFactory:
    profiles_dir = tmp_path / "cookies"
    profiles_dir.mkdir()
    db_path = tmp_path / "test_factory.db"
    return AccountFactory(db_path=db_path, profiles_dir=profiles_dir)


# ── Tests ───────────────────────────────────────────────────────────────────

def test_create_profile_inserts_sqlite(factory, tmp_path):
    """create_profile() insère dans SQLite avec status=creating."""
    config = ProfileConfig(geo_id="be-brussels", proxy_country="BE")
    pid = factory.create_profile(config)

    conn = sqlite3.connect(str(factory.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM profiles WHERE profile_id=?", (pid,)).fetchone()
    conn.close()

    assert row is not None
    assert row["status"] == CREATING


def test_create_profile_returns_profile_id(factory):
    config = ProfileConfig(geo_id="fr-paris", proxy_country="FR", profile_id="prof-fr-001")
    pid = factory.create_profile(config)
    assert pid == "prof-fr-001"


@pytest.mark.asyncio
async def test_run_warm_up_sets_status_warming(factory):
    """run_warm_up() doit mettre status=warming après le warm_up."""
    config = ProfileConfig(geo_id="de-berlin", proxy_country="DE")
    pid = factory.create_profile(config)

    with patch.object(factory._pm, "warm_up", new=AsyncMock(return_value={
        "profile_id": pid, "sites_visited": 5, "cookies_collected": 8, "status": "warmed"
    })):
        result = await factory.run_warm_up(pid)

    assert result["status"] == WARMING
    profile = factory._get_profile(pid)
    assert profile["status"] == WARMING
    assert profile["warmed"] == 1


@pytest.mark.asyncio
async def test_daily_micro_session_increments_age(factory):
    """daily_micro_session() incrémente age_days."""
    config = ProfileConfig(geo_id="nl-amsterdam", proxy_country="NL")
    pid = factory.create_profile(config)
    factory._update_status(pid, WARMING)

    with patch.object(factory._pm, "micro_session", new=AsyncMock(return_value={
        "profile_id": pid, "sites_visited": 2
    })):
        result = await factory.daily_micro_session(pid)

    assert result["age_days"] == 1


@pytest.mark.asyncio
async def test_transition_warming_to_ready_at_day_7(factory):
    """status=warming + age_days >= 7 → status=ready."""
    config = ProfileConfig(geo_id="be-brussels", proxy_country="BE")
    pid = factory.create_profile(config)
    factory._update_status(pid, WARMING)
    # Set age_days to 6 directly
    with sqlite3.connect(str(factory.db_path)) as conn:
        conn.execute("UPDATE profiles SET age_days=6 WHERE profile_id=?", (pid,))

    with patch.object(factory._pm, "micro_session", new=AsyncMock(return_value={
        "profile_id": pid, "sites_visited": 2
    })):
        result = await factory.daily_micro_session(pid)

    assert result["status"] == READY
    assert factory._get_profile(pid)["status"] == READY


@pytest.mark.asyncio
async def test_transition_ready_to_senior_at_day_30(factory):
    """status=ready + age_days >= 30 → status=senior."""
    config = ProfileConfig(geo_id="fr-paris", proxy_country="FR")
    pid = factory.create_profile(config)
    factory._update_status(pid, READY)
    with sqlite3.connect(str(factory.db_path)) as conn:
        conn.execute("UPDATE profiles SET age_days=29 WHERE profile_id=?", (pid,))

    with patch.object(factory._pm, "micro_session", new=AsyncMock(return_value={
        "profile_id": pid, "sites_visited": 2
    })):
        result = await factory.daily_micro_session(pid)

    assert result["status"] == SENIOR


@pytest.mark.asyncio
async def test_transition_to_recycle_at_day_90(factory):
    """age_days >= 90 → status=recycle, peu importe le statut actuel."""
    config = ProfileConfig(geo_id="gb-london", proxy_country="GB")
    pid = factory.create_profile(config)
    factory._update_status(pid, SENIOR)
    with sqlite3.connect(str(factory.db_path)) as conn:
        conn.execute("UPDATE profiles SET age_days=89 WHERE profile_id=?", (pid,))

    with patch.object(factory._pm, "micro_session", new=AsyncMock(return_value={
        "profile_id": pid, "sites_visited": 2
    })):
        result = await factory.daily_micro_session(pid)

    assert result["status"] == RECYCLE


def test_get_ready_profiles_filters_correctly(factory):
    """get_ready_profiles() retourne uniquement ready et senior."""
    for country, status, age in [("BE", READY, 10), ("FR", WARMING, 5), ("DE", SENIOR, 35)]:
        cfg = ProfileConfig(geo_id=f"{country.lower()}-city", proxy_country=country)
        pid = factory.create_profile(cfg)
        factory._update_status(pid, status)
        with sqlite3.connect(str(factory.db_path)) as conn:
            conn.execute("UPDATE profiles SET age_days=? WHERE profile_id=?", (age, pid))

    ready = factory.get_ready_profiles(min_age_days=1)
    statuses = {p["status"] for p in ready}
    assert statuses <= {READY, SENIOR}
    assert WARMING not in statuses


def test_get_best_for_domain_returns_de_for_ebay_de(factory):
    """get_best_for_domain('ebay.de') → profil proxy_country=DE."""
    for country in ["BE", "DE", "FR"]:
        cfg = ProfileConfig(geo_id=f"{country.lower()}-city", proxy_country=country)
        pid = factory.create_profile(cfg)
        factory._update_status(pid, READY)
        with sqlite3.connect(str(factory.db_path)) as conn:
            conn.execute(
                "UPDATE profiles SET warmed=1, age_days=10 WHERE profile_id=?", (pid,)
            )
    factory._pm._load_meta()

    result = factory.get_best_for_domain("ebay.de")
    assert result is not None
    assert result["proxy_country"] == "DE"


def test_get_best_for_domain_returns_fr_for_leboncoin(factory):
    """get_best_for_domain('leboncoin.fr') → profil proxy_country=FR."""
    for country in ["BE", "DE", "FR"]:
        cfg = ProfileConfig(geo_id=f"{country.lower()}-city", proxy_country=country)
        pid = factory.create_profile(cfg)
        factory._update_status(pid, READY)
        with sqlite3.connect(str(factory.db_path)) as conn:
            conn.execute(
                "UPDATE profiles SET warmed=1, age_days=10 WHERE profile_id=?", (pid,)
            )
    factory._pm._load_meta()

    result = factory.get_best_for_domain("leboncoin.fr")
    assert result is not None
    assert result["proxy_country"] == "FR"


@pytest.mark.asyncio
async def test_daily_factory_run_creates_and_ages(factory):
    """daily_factory_run() crée + vieillit profils, retourne rapport complet."""
    with patch.object(factory._pm, "warm_up", new=AsyncMock(side_effect=lambda pid: {
        "profile_id": pid, "sites_visited": 5, "cookies_collected": 8, "status": "warmed"
    })), patch.object(factory._pm, "micro_session", new=AsyncMock(side_effect=lambda pid: {
        "profile_id": pid, "sites_visited": 2
    })):
        report = await factory.daily_factory_run(new_profiles_count=2)

    assert len(report["created"]) == 2
    assert len(report["warmed"]) == 2  # les 2 nouveaux sont passés par warm_up
    assert "errors" in report


@pytest.mark.asyncio
async def test_daily_factory_run_fail_safe(factory):
    """Si warm_up échoue sur 1 profil, daily_factory_run continue les autres."""
    call_count = {"n": 0}

    async def _failing_warm_up(pid):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated warm-up failure")
        return {"profile_id": pid, "sites_visited": 5, "cookies_collected": 8, "status": "warmed"}

    with patch.object(factory._pm, "warm_up", new=_failing_warm_up), \
         patch.object(factory._pm, "micro_session", new=AsyncMock(return_value={
             "profile_id": "x", "sites_visited": 2
         })):
        report = await factory.daily_factory_run(new_profiles_count=2)

    assert len(report["errors"]) >= 1
    assert len(report["warmed"]) >= 1  # le 2e a réussi malgré l'échec du 1er


# ── Bridge endpoint tests ────────────────────────────────────────────────────

@pytest.fixture
def client():
    import os
    os.environ["BRIDGE_AUTH_TOKEN"] = "test-token-12345678901234567890123456789012"
    from bridge.app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token-12345678901234567890123456789012"}


def test_factory_stats_endpoint(client, auth_headers):
    """GET /factory/stats retourne comptes par statut."""
    resp = client.get("/factory/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "by_status" in data


def test_factory_create_endpoint(client, auth_headers):
    """POST /factory/create crée N profils."""
    resp = client.post(
        "/factory/create",
        json={"geo_id": "be-brussels", "proxy_country": "BE", "count": 2},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert len(data["created"]) == 2


def test_factory_profiles_status_filter(client, auth_headers):
    """GET /factory/profiles?status=creating filtre correctement."""
    client.post(
        "/factory/create",
        json={"geo_id": "fr-paris", "proxy_country": "FR", "count": 1},
        headers=auth_headers,
    )
    resp = client.get("/factory/profiles?status=creating", headers=auth_headers)
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert all(p["status"] == "creating" for p in profiles)
