"""ProxyRotator: round-robin proxy selection with per-host rate cap and SQLite tracking."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class ProxyRotator:
    def __init__(self, pool_file: Path, tier: str):
        """Load pool.json, filter to tier, open risk_db for tracking."""
        data = json.loads(pool_file.read_text(encoding="utf-8"))
        tiers = data.get("tiers", {})
        self._proxies = [
            p for p in tiers.get(tier, []) if p.get("active")
        ]
        self._tier = tier
        self._idx = 0

        db_path = pool_file.parent.parent.parent / "storage" / "risk_db.sqlite"
        self._db = sqlite3.connect(str(db_path))
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS proxy_use (
                proxy_url TEXT,
                host      TEXT,
                ts        INTEGER,
                status    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_proxy_use_lookup ON proxy_use(proxy_url, host, ts);
        """)

    def pick(self, host: str, max_per_host_per_hour: int = 20) -> dict | None:
        """Round-robin selection with per-host hourly cap. Returns proxy dict or None."""
        if not self._proxies:
            return None

        cutoff = int(time.time()) - 3600
        n = len(self._proxies)

        for attempt in range(n):
            candidate_idx = (self._idx + attempt) % n
            candidate = self._proxies[candidate_idx]

            if candidate.get("provider") == "brightdata":
                from network.proxy_pool.brightdata import build_proxy_url
                url = build_proxy_url(
                    country=candidate.get("country"),
                    tier=self._tier,
                )
                if not url:
                    return None  # credentials not configured → no Bright Data
                candidate = {**candidate, "url": url}

            proxy_url = candidate["url"]

            cur = self._db.execute(
                "SELECT COUNT(*) FROM proxy_use WHERE proxy_url = ? AND host = ? AND ts >= ?",
                (proxy_url, host, cutoff),
            )
            count = cur.fetchone()[0]

            if count < max_per_host_per_hour:
                self._idx = (candidate_idx + 1) % n
                return candidate

        return None

    def report(self, proxy_url: str, host: str, status: int) -> None:
        """Record proxy usage in proxy_use table."""
        self._db.execute(
            "INSERT INTO proxy_use VALUES (?, ?, ?, ?)",
            (proxy_url, host, int(time.time()), status),
        )
        self._db.commit()
