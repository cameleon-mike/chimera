"""AccountFactory — orchestrates profile creation, warm-up and daily aging."""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.account_factory.profile_config import ProfileConfig, SUPPORTED_COUNTRIES
from tools.screenshot_runner.profile_manager import ProfileManager

# Status lifecycle
CREATING = "creating"
WARMING  = "warming"
READY    = "ready"
SENIOR   = "senior"
RECYCLE  = "recycle"

THRESHOLDS = {
    "warming": 1,   # age_days >= 1 et status=creating → warming (après warm_up)
    "ready":   7,   # age_days >= 7 et status=warming → ready
    "senior":  30,  # age_days >= 30 et status=ready → senior
    "recycle": 90,  # age_days >= 90 → recycle
}


class AccountFactory:

    def __init__(
        self,
        db_path: Path,
        profiles_dir: Path,
        settings: Any | None = None,
    ):
        self.db_path = db_path
        self.profiles_dir = profiles_dir
        self.settings = settings
        # ProfileManager shares the same db_path → same profiles table
        self._pm = ProfileManager(profiles_dir=profiles_dir, db_path=db_path)

    # ------------------------------------------------------------------ helpers

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_profile(self, profile_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def _update_status(self, profile_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE profiles SET status=? WHERE profile_id=?",
                (status, profile_id),
            )
        if profile_id in self._pm.meta:
            self._pm.meta[profile_id]["status"] = status

    def _increment_age(self, profile_id: str) -> int:
        with self._conn() as conn:
            conn.execute(
                "UPDATE profiles SET age_days=age_days+1, last_active=? WHERE profile_id=?",
                (datetime.now(timezone.utc).isoformat(), profile_id),
            )
            row = conn.execute(
                "SELECT age_days FROM profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
        age = row["age_days"] if row else 0
        if profile_id in self._pm.meta:
            self._pm.meta[profile_id]["age_days"] = age
        return age

    # ------------------------------------------------------------------ Phase 1

    def create_profile(self, config: ProfileConfig) -> str:
        """Create profile dir + INSERT in SQLite with status=creating."""
        profile_path = self.profiles_dir / config.profile_id
        profile_path.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO profiles
                   (profile_id, geo_id, proxy_country, ua_profile_id, status,
                    age_days, created_at, last_active, last_used, warmed,
                    cookies_count, extensions_json, linked_account_json)
                   VALUES (?,?,?,?,?,0,?,?,NULL,0,0,?,?)""",
                (
                    config.profile_id,
                    config.geo_id,
                    config.proxy_country,
                    config.ua_profile_id,
                    CREATING,
                    now, now,
                    json.dumps(config.extensions),
                    json.dumps(config.linked_account),
                ),
            )
        # Keep pm.meta in sync
        self._pm._load_meta()
        return config.profile_id

    # ------------------------------------------------------------------ Phase 2

    async def run_warm_up(self, profile_id: str) -> dict:
        """Warm up a profile and set status=warming."""
        # PM warm_up handles Playwright — won't override factory status
        result = await self._pm.warm_up(profile_id)

        # Update cookies_count in DB
        cookies = result.get("cookies_collected", 0)
        with self._conn() as conn:
            conn.execute(
                "UPDATE profiles SET warmed=1, cookies_count=?, last_active=? WHERE profile_id=?",
                (cookies, datetime.now(timezone.utc).isoformat(), profile_id),
            )
        self._update_status(profile_id, WARMING)

        result["status"] = WARMING
        return result

    # ------------------------------------------------------------------ Phase 3

    async def daily_micro_session(self, profile_id: str) -> dict:
        """Daily aging: micro_session + age increment + status transitions."""
        result = await self._pm.micro_session(profile_id)
        age = self._increment_age(profile_id)

        profile = self._get_profile(profile_id)
        current_status = profile["status"] if profile else WARMING
        new_status = current_status

        if age >= THRESHOLDS["recycle"]:
            new_status = RECYCLE
        elif age >= THRESHOLDS["senior"] and current_status == READY:
            new_status = SENIOR
        elif age >= THRESHOLDS["ready"] and current_status == WARMING:
            new_status = READY

        if new_status != current_status:
            self._update_status(profile_id, new_status)

        result.update({"age_days": age, "status": new_status})
        return result

    # ------------------------------------------------------------------ Phase 4

    def get_ready_profiles(self, min_age_days: int = 1) -> list[dict]:
        """Profiles with status in (ready, senior) and age >= min_age_days."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles WHERE status IN ('ready','senior') AND age_days >= ?",
                (min_age_days,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_best_for_domain(self, domain: str) -> dict | None:
        """Delegate to ProfileManager geo-matching, then check factory-managed profiles."""
        result = self._pm.get_best_profile_for_domain(domain)
        if result:
            return result
        # Fallback: any ready/senior profile
        candidates = self.get_ready_profiles(min_age_days=0)
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.get("age_days", 0))

    # ------------------------------------------------------------------ Cron

    async def daily_factory_run(self, new_profiles_count: int = 2) -> dict:
        """Full daily orchestration — FAIL-SAFE (one profile failure doesn't stop others)."""
        report: dict[str, list] = {
            "created": [],
            "warmed": [],
            "aged": [],
            "recycled": [],
            "errors": [],
        }

        # 1. Create new profiles (random geo from supported countries)
        for _ in range(new_profiles_count):
            country = random.choice(SUPPORTED_COUNTRIES)
            city = country.lower() + "-city"
            config = ProfileConfig(geo_id=f"{country.lower()}-{city}", proxy_country=country)
            try:
                pid = self.create_profile(config)
                report["created"].append(pid)
            except Exception as exc:
                report["errors"].append(f"create: {exc}")

        # 2. Warm up profiles with status=creating
        with self._conn() as conn:
            creating = [
                r["profile_id"]
                for r in conn.execute(
                    "SELECT profile_id FROM profiles WHERE status=?", (CREATING,)
                ).fetchall()
            ]
        for pid in creating:
            try:
                await self.run_warm_up(pid)
                report["warmed"].append(pid)
            except Exception as exc:
                report["errors"].append(f"warm_up {pid}: {exc}")

        # 3. Micro-sessions for warming/ready/senior profiles
        with self._conn() as conn:
            active = [
                r["profile_id"]
                for r in conn.execute(
                    "SELECT profile_id FROM profiles WHERE status IN (?,?,?)",
                    (WARMING, READY, SENIOR),
                ).fetchall()
            ]
        for pid in active:
            try:
                result = await self.daily_micro_session(pid)
                if result.get("status") == RECYCLE:
                    report["recycled"].append(pid)
                else:
                    report["aged"].append(pid)
            except Exception as exc:
                report["errors"].append(f"micro_session {pid}: {exc}")

        return report

    def list_all_profiles(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM profiles").fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            counts = {}
            for status in [CREATING, WARMING, READY, SENIOR, RECYCLE, "created", "warmed"]:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM profiles WHERE status=?", (status,)
                ).fetchone()
                counts[status] = row["c"] if row else 0
            total = conn.execute("SELECT COUNT(*) as c FROM profiles").fetchone()["c"]
            oldest = conn.execute(
                "SELECT profile_id FROM profiles ORDER BY age_days DESC LIMIT 1"
            ).fetchone()
            newest = conn.execute(
                "SELECT profile_id FROM profiles ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
        return {
            "total": total,
            "by_status": counts,
            "oldest_profile": oldest["profile_id"] if oldest else None,
            "newest_profile": newest["profile_id"] if newest else None,
        }
