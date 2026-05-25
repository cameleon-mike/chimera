"""ProfileManager — browser profile creation, warm-up, and aging."""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from network.proxy_pool.brightdata import get_proxy_for_profile
from tools.screenshot_runner.stealth.loader import load_stealth_script, session_seed_from_id

_LOCAL_WARMUP_SITES: dict[str, list[str]] = {
    "BE": [
        "https://www.rtbf.be",
        "https://www.lesoir.be",
        "https://www.hln.be",
        "https://www.immoweb.be",
    ],
    "FR": [
        "https://www.lemonde.fr",
        "https://www.lefigaro.fr",
        "https://www.leboncoin.fr",
    ],
    "DE": [
        "https://www.spiegel.de",
        "https://www.heise.de",
        "https://www.ebay.de",
    ],
    "GB": [
        "https://www.bbc.co.uk",
        "https://www.theguardian.com",
        "https://www.gumtree.com",
    ],
    "NL": [
        "https://www.nu.nl",
        "https://www.marktplaats.nl",
        "https://www.tweakers.net",
    ],
}

_GENERIC_WARMUP_SITES = [
    "https://www.google.com",
    "https://www.wikipedia.org",
    "https://www.youtube.com",
]

_COOKIE_COLLECTION_SITES = [
    "https://www.google.com",
    "https://www.facebook.com",
    "https://www.youtube.com",
]

_TLD_TO_COUNTRY = {
    "FR": "FR",
    "DE": "DE",
    "BE": "BE",
    "NL": "NL",
    "UK": "GB",  # .co.uk → tld = "uk"
    "GB": "GB",
    "COM": None,  # generic — no geo preference
}

# Statuses managed by AccountFactory — ProfileManager must not override them
_PROFILE_STATUSES_FACTORY = {"creating", "warming", "ready", "senior", "recycle"}


class ProfileManager:
    def __init__(self, profiles_dir: Path | None = None, db_path: Path | None = None):
        if profiles_dir is None:
            from bridge.config import get_settings
            profiles_dir = get_settings().cookies_dir
        self.profiles_dir = profiles_dir
        # db_path local if not provided — ensures test isolation
        self._db_path = db_path if db_path is not None else profiles_dir / "profiles.db"
        # Kept for backward compat — always in sync with SQLite
        self.meta: dict[str, dict[str, Any]] = {}
        self.meta_file = profiles_dir / "profiles_meta.json"  # kept for migration check
        self._init_db()
        self._load_meta()

    # ------------------------------------------------------------------ DB init

    def _init_db(self) -> None:
        """Create SQLite tables (idempotent)."""
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    profile_id          TEXT PRIMARY KEY,
                    geo_id              TEXT NOT NULL DEFAULT 'fr-paris',
                    proxy_country       TEXT NOT NULL DEFAULT 'FR',
                    ua_profile_id       TEXT NOT NULL DEFAULT 'chrome127-win',
                    status              TEXT DEFAULT 'created',
                    age_days            INTEGER DEFAULT 0,
                    created_at          TEXT,
                    last_active         TEXT,
                    last_used           TEXT,
                    warmed              INTEGER DEFAULT 0,
                    cookies_count       INTEGER DEFAULT 0,
                    extensions_json     TEXT DEFAULT '[]',
                    linked_account_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_profiles_status ON profiles(status);
                CREATE INDEX IF NOT EXISTS idx_profiles_country ON profiles(proxy_country);
            """)

    # ------------------------------------------------------------------ Load / Save

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite Row to a Python dict (warmed INTEGER → bool, _json cols → parsed)."""
        d = dict(row)
        d["warmed"] = bool(d.get("warmed", 0))
        d["extensions"] = json.loads(d.pop("extensions_json", "[]"))
        d["linked_account"] = json.loads(d.pop("linked_account_json", "{}"))
        return d

    def _load_meta(self) -> None:
        """Migration JSON→SQLite then load all rows into self.meta."""
        # Migration: if JSON exists and table is empty → migrate then delete JSON
        if self.meta_file.exists():
            with sqlite3.connect(str(self._db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            if count == 0:
                try:
                    old_meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
                    with sqlite3.connect(str(self._db_path)) as conn:
                        for pid, data in old_meta.items():
                            conn.execute(
                                """INSERT OR IGNORE INTO profiles
                                   (profile_id, geo_id, proxy_country, ua_profile_id,
                                    status, age_days, created_at, last_active, last_used,
                                    warmed, cookies_count, extensions_json, linked_account_json)
                                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    pid,
                                    data.get("geo_id", "fr-paris"),
                                    data.get("proxy_country", "FR"),
                                    data.get("ua_profile_id", "chrome127-win"),
                                    data.get("status", "created"),
                                    data.get("age_days", 0),
                                    data.get("created_at"),
                                    data.get("last_active"),
                                    data.get("last_used"),
                                    1 if data.get("warmed") else 0,
                                    data.get("cookies_count", 0),
                                    json.dumps(data.get("extensions", [])),
                                    json.dumps(data.get("linked_account", {})),
                                ),
                            )
                except Exception:
                    pass
                finally:
                    try:
                        self.meta_file.unlink()
                    except Exception:
                        pass

        # Load all rows from SQLite into self.meta
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM profiles").fetchall()
        self.meta = {row["profile_id"]: self._row_to_dict(row) for row in rows}

    def _save_meta(self) -> None:
        """Write self.meta entirely to SQLite via INSERT OR REPLACE."""
        with sqlite3.connect(str(self._db_path)) as conn:
            for pid, data in self.meta.items():
                conn.execute(
                    """INSERT OR REPLACE INTO profiles
                       (profile_id, geo_id, proxy_country, ua_profile_id,
                        status, age_days, created_at, last_active, last_used,
                        warmed, cookies_count, extensions_json, linked_account_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        pid,
                        data.get("geo_id", "fr-paris"),
                        data.get("proxy_country", "FR"),
                        data.get("ua_profile_id", "chrome127-win"),
                        data.get("status", "created"),
                        data.get("age_days", 0),
                        data.get("created_at"),
                        data.get("last_active"),
                        data.get("last_used"),
                        1 if data.get("warmed") else 0,
                        data.get("cookies_count", 0),
                        json.dumps(data.get("extensions", [])),
                        json.dumps(data.get("linked_account", {})),
                    ),
                )

    # ------------------------------------------------------------------ CRUD

    def register_profile(self, profile_id: str, config: dict, status: str = "created") -> None:
        """Register a new profile in the registry (idempotent — INSERT OR IGNORE)."""
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "profile_id":    profile_id,
            "geo_id":        config.get("geo_id", "fr-paris"),
            "proxy_country": config.get("proxy_country", "FR"),
            "ua_profile_id": config.get("ua_profile_id", "chrome127-win"),
            "status":        status,
            "age_days":      0,
            "created_at":    now,
            "last_active":   None,
            "last_used":     None,
            "warmed":        False,
            "cookies_count": 0,
            "extensions":    [],
            "linked_account": {},
        }
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO profiles
                   (profile_id, geo_id, proxy_country, ua_profile_id,
                    status, age_days, created_at, last_active, last_used,
                    warmed, cookies_count, extensions_json, linked_account_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    profile_id,
                    entry["geo_id"],
                    entry["proxy_country"],
                    entry["ua_profile_id"],
                    entry["status"],
                    entry["age_days"],
                    entry["created_at"],
                    entry["last_active"],
                    entry["last_used"],
                    0,
                    0,
                    json.dumps([]),
                    json.dumps({}),
                ),
            )
        # Keep self.meta in sync — INSERT OR IGNORE means existing entries are untouched
        if profile_id not in self.meta:
            self.meta[profile_id] = entry

    def update_profile_status(self, profile_id: str, status: str) -> None:
        """Update status in SQLite and in-memory meta."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE profiles SET status=? WHERE profile_id=?",
                (status, profile_id),
            )
        if profile_id in self.meta:
            self.meta[profile_id]["status"] = status

    def increment_age(self, profile_id: str) -> int:
        """Increment age_days by 1 in SQLite and in-memory. Returns new age_days."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE profiles SET age_days=age_days+1 WHERE profile_id=?",
                (profile_id,),
            )
            row = conn.execute(
                "SELECT age_days FROM profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
        age = row[0] if row else 0
        if profile_id in self.meta:
            self.meta[profile_id]["age_days"] = age
        return age

    # ------------------------------------------------------------------ Playwright

    async def warm_up(self, profile_id: str) -> dict:
        """Full warm-up sequence (10–15 min): cookie collection + local sites.

        Fails silently per site — an inaccessible site is skipped without raising.
        """
        meta = self.meta.get(profile_id, {})
        proxy_country = meta.get("proxy_country", "FR")
        profile_path = self.profiles_dir / profile_id
        profile_path.mkdir(parents=True, exist_ok=True)

        proxy = get_proxy_for_profile(proxy_country, "residential")
        seed = session_seed_from_id(profile_id)
        stealth = load_stealth_script(session_seed=seed)

        local_sites = _LOCAL_WARMUP_SITES.get(proxy_country, _GENERIC_WARMUP_SITES)
        sites_to_visit = _COOKIE_COLLECTION_SITES + local_sites + _GENERIC_WARMUP_SITES

        cookies_collected: list = []

        async with async_playwright() as pw:
            launch_kwargs = {
                "user_data_dir": str(profile_path),
                "headless": True,
                "locale": meta.get("locale", "fr-FR"),
                "timezone_id": meta.get("timezone", "Europe/Paris"),
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            }
            if proxy is not None:
                launch_kwargs["proxy"] = proxy

            ctx = await pw.chromium.launch_persistent_context(**launch_kwargs)
            await ctx.add_init_script(stealth)

            for site in sites_to_visit:
                try:
                    page = await ctx.new_page()
                    await page.goto(site, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(random.randint(2000, 4000))
                    for _ in range(random.randint(1, 3)):
                        await page.mouse.wheel(0, random.randint(200, 500))
                        await page.wait_for_timeout(random.randint(500, 1500))
                    await page.close()
                except Exception:
                    pass  # inaccessible site — skip silently

            cookies_collected = await ctx.cookies()
            await ctx.close()

        # Update in-memory meta
        if profile_id in self.meta:
            self.meta[profile_id]["warmed"] = True
            self.meta[profile_id]["last_active"] = datetime.now(timezone.utc).isoformat()
            self.meta[profile_id]["cookies_count"] = len(cookies_collected)
            # Only set status if NOT factory-managed
            current_status = self.meta[profile_id].get("status", "created")
            if current_status not in _PROFILE_STATUSES_FACTORY:
                self.meta[profile_id]["status"] = "warmed"
        self._save_meta()

        return {
            "profile_id":        profile_id,
            "sites_visited":     len(sites_to_visit),
            "cookies_collected": len(cookies_collected),
            "status":            self.meta.get(profile_id, {}).get("status", "warmed"),
        }

    async def micro_session(self, profile_id: str) -> dict:
        """Daily aging session — 2–3 pages, ~2 min."""
        meta = self.meta.get(profile_id, {})
        proxy_country = meta.get("proxy_country", "FR")
        profile_path = self.profiles_dir / profile_id

        sites = _LOCAL_WARMUP_SITES.get(proxy_country, _GENERIC_WARMUP_SITES)
        sites_today = random.sample(sites, min(2, len(sites)))

        proxy = get_proxy_for_profile(proxy_country, "residential")
        stealth = load_stealth_script(session_seed=session_seed_from_id(profile_id))

        async with async_playwright() as pw:
            launch_kwargs = {
                "user_data_dir": str(profile_path),
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            }
            if proxy is not None:
                launch_kwargs["proxy"] = proxy

            ctx = await pw.chromium.launch_persistent_context(**launch_kwargs)
            await ctx.add_init_script(stealth)
            for site in sites_today:
                try:
                    page = await ctx.new_page()
                    await page.goto(site, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(random.randint(3000, 6000))
                    await page.close()
                except Exception:
                    pass
            await ctx.close()

        now = datetime.now(timezone.utc).isoformat()
        if profile_id in self.meta:
            self.meta[profile_id]["last_active"] = now
            # Increment in-memory only — AccountFactory._increment_age() owns the SQLite increment.
            # When used standalone (no AccountFactory), age_days stays accurate in memory
            # but the caller is responsible for persisting via _save_meta() if needed.
            self.meta[profile_id]["age_days"] = self.meta[profile_id].get("age_days", 0) + 1
        # Persist only last_active — age_days increment is NOT written to SQLite here to
        # avoid double-counting when AccountFactory._increment_age() runs after this call.
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "UPDATE profiles SET last_active=? WHERE profile_id=?",
                (now, profile_id),
            )

        return {"profile_id": profile_id, "sites_visited": len(sites_today)}

    # ------------------------------------------------------------------ Queries

    def get_ready_profiles(self, min_age_days: int = 1) -> list[dict]:
        """Return warmed profiles that meet the minimum age requirement.

        Queries SQLite directly for accuracy.
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM profiles
                   WHERE status IN ('ready','senior','warmed','created')
                   AND age_days >= ?
                   AND warmed = 1""",
                (min_age_days,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_best_profile_for_domain(self, domain: str) -> dict | None:
        """Select the best profile for a domain.

        Priority:
        1. Geo-coherent profile (ebay.de → DE, ebay.fr → FR)
        2. Warmed profiles only
        3. Highest age_days (most credible history)
        """
        tld = domain.rsplit(".", 1)[-1].upper()
        preferred_country = _TLD_TO_COUNTRY.get(tld)

        candidates = [p for p in self.meta.values() if p.get("warmed")]

        if preferred_country:
            geo_match = [p for p in candidates if p.get("proxy_country") == preferred_country]
            if geo_match:
                candidates = geo_match

        if not candidates:
            return None
        return max(candidates, key=lambda p: p.get("age_days", 0))

    def list_profiles(self) -> list[dict]:
        return list(self.meta.values())
