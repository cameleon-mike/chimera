"""NavigatorAgent — orchestrates FLIPMACHINE pipeline in one call."""
from __future__ import annotations

import logging
import sqlite3
import time

import requests

logger = logging.getLogger(__name__)

_MARKETPLACE_DOMAIN: dict[str, str] = {
    "EBAY_FR": "ebay.fr",
    "EBAY_DE": "ebay.de",
    "EBAY_GB": "ebay.co.uk",
    "EBAY_BE": "ebay.be",
    "EBAY_NL": "ebay.nl",
}


class NavigatorAgent:
    def __init__(self, settings, db_path):
        self._settings = settings
        self._db_path = str(db_path)
        self._base_url = f"http://{settings.bridge_host}:{settings.bridge_port}"
        self._headers = {"Authorization": f"Bearer {settings.bridge_auth_token}"}

    def run(
        self,
        query: str,
        max_price: float | None = None,
        marketplace: str = "EBAY_FR",
    ) -> dict:
        """Full FLIPMACHINE pipeline: probe → scrape → score → top deals.
        Never raises — all failures are caught and degrade gracefully.
        """
        t0 = time.time()

        # 1. Probe marketplace
        domain = _MARKETPLACE_DOMAIN.get(marketplace, "ebay.fr")
        probe_risk = self._probe(domain)

        # 2. Scrape + ingest via /aggregate/search
        total_scraped = 0
        items: list[dict] = []
        try:
            resp = requests.get(
                f"{self._base_url}/aggregate/search",
                params={"q": query, "marketplace": marketplace, "ingest": "true"},
                headers=self._headers,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            total_scraped = data.get("total_items", 0)
            items = data.get("items", [])
        except Exception as exc:
            logger.warning("navigator_scrape_error: %s", repr(exc))

        # 3. Filter by max_price
        if max_price is not None:
            items = [
                it for it in items
                if (
                    it.get("price")
                    and it["price"].get("value") is not None
                    and it["price"]["value"] <= max_price
                )
            ]

        # 4. Score items with ePID against SQLite epid_stats
        deals: list[dict] = []
        total_scored = 0

        scoreable = [
            it for it in items
            if it.get("epid")
            and it.get("price")
            and it["price"].get("value")
            and it["price"]["value"] > 0
        ]

        if scoreable:
            from tools.decision_agent.scorer import FlipScorer

            scorer = FlipScorer()
            stats_by_epid = self._load_epid_stats([it["epid"] for it in scoreable])

            for item in scoreable:
                stats = stats_by_epid.get(item["epid"])
                if not stats:
                    continue
                total_scored += 1
                result = scorer.score(item["price"]["value"], stats)
                if result["decision"] in ("BUY", "OFFER"):
                    deals.append({
                        "epid": item["epid"],
                        "title": item.get("title"),
                        "listed_price": item["price"]["value"],
                        "link": item.get("link"),
                        **result,
                    })

        deals.sort(key=lambda d: d["confidence"], reverse=True)
        deals = deals[:10]

        pipeline_ms = max(1, int((time.time() - t0) * 1000))

        # Build one-line summary
        if deals:
            best = deals[0]
            margin = best.get("margin_eur") or 0.0
            summary = (
                f"{len(deals)} deals found — "
                f"best: {best['decision']} at {best['listed_price']:.0f}€, "
                f"margin {margin:.0f}€"
            )
        elif total_scraped == 0:
            summary = "no items scraped"
        else:
            summary = f"no deals — {total_scraped} scraped, {total_scored} scored"

        return {
            "query": query,
            "pipeline_ms": pipeline_ms,
            "probe_risk": probe_risk,
            "total_scraped": total_scraped,
            "total_scored": total_scored,
            "deals": deals,
            "summary": summary,
        }

    def _probe(self, domain: str) -> float:
        """Call bridge /probe/{domain}. Returns risk_score or 0.0 on any error."""
        try:
            resp = requests.get(
                f"{self._base_url}/probe/{domain}",
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
            return float(resp.json().get("risk_score", 0.0))
        except Exception as exc:
            logger.warning("navigator_probe_error: %s", repr(exc))
            return 0.0

    def _load_epid_stats(self, epids: list[str]) -> dict[str, dict]:
        """Batch load epid_stats from SQLite. Returns empty dict on error."""
        unique = list(dict.fromkeys(epids))  # preserve order, deduplicate
        if not unique:
            return {}
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                placeholders = ",".join("?" * len(unique))
                cur = conn.execute(
                    f"""
                    SELECT epid, brand, model, total_items, currency,
                           median_price, q1_price, q2_price, q3_price, q4_price,
                           avg_sell_days, min_sell_days, max_sell_days,
                           sell_days_sample, last_updated
                    FROM epid_stats WHERE epid IN ({placeholders})
                    """,
                    unique,
                )
                result: dict[str, dict] = {}
                for row in cur.fetchall():
                    result[row[0]] = {
                        "epid": row[0], "brand": row[1], "model": row[2],
                        "total_items": row[3], "currency": row[4],
                        "median_price": row[5], "q1_price": row[6],
                        "q2_price": row[7], "q3_price": row[8], "q4_price": row[9],
                        "avg_sell_days": row[10], "min_sell_days": row[11],
                        "max_sell_days": row[12], "sell_days_sample": row[13],
                        "last_updated": row[14],
                    }
                return result
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("navigator_db_error: %s", repr(exc))
            return {}
