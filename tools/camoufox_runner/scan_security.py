from __future__ import annotations

import asyncio
from datetime import datetime, timezone

# Browser-free caniscrape analyzers (verified). Imported at module level so
# tests can monkeypatch them. If caniscrape import fails, fall back to None.
try:
    from caniscrape.analyzers.tls_analyzer import analyze_tls_fingerprint
    from caniscrape.analyzers.robots_checker import check_robots_txt
except Exception:  # pragma: no cover
    analyze_tls_fingerprint = None
    check_robots_txt = None

try:
    from wafw00f.main import WAFW00F
except Exception:  # pragma: no cover
    WAFW00F = None


class ScanSecurity:
    """Browser-free security scanner: caniscrape (TLS/robots) + wafw00f (WAF)."""

    def __init__(self, settings):
        self.settings = settings

    def scan(self, url: str) -> dict:
        caniscrape_result = self._caniscrape_scan(url)
        wafw00f_result = self._wafw00f_scan(url)

        waf = wafw00f_result.get("waf_detected")
        captcha = bool(
            caniscrape_result.get("captcha", {}).get("captcha_detected", False)
        )
        tls_fingerprinting = (
            caniscrape_result.get("tls", {}).get("status") == "active"
        )
        difficulty = self._calculate_difficulty(caniscrape_result, wafw00f_result)

        return {
            "url": url,
            "waf": waf,
            "captcha": captcha,
            "tls_fingerprinting": tls_fingerprinting,
            "difficulty": difficulty,
            "proxy_recommendation": self._recommend_proxy(waf),
            "tool_recommendation": self._recommend_tool(difficulty),
            "raw_caniscrape": caniscrape_result,
            "raw_wafw00f": wafw00f_result,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def _caniscrape_scan(self, url: str) -> dict:
        """Run browser-free caniscrape analyzers. Returns {} on any exception."""
        try:
            if analyze_tls_fingerprint is None or check_robots_txt is None:
                return {}
            tls = asyncio.run(analyze_tls_fingerprint(url))
            robots = check_robots_txt(url)
            return {"tls": tls, "robots": robots}
        except Exception:
            return {}

    def _wafw00f_scan(self, url: str) -> dict:
        """Detect WAF via wafw00f WAFW00F class. Returns {} on any exception."""
        try:
            if WAFW00F is None:
                return {}
            attacker = WAFW00F(target=url, timeout=10)
            if attacker.rq is None:
                return {"waf_detected": None}
            detected, _ = attacker.identwaf(findall=False)
            return {"waf_detected": detected[0] if detected else None}
        except Exception:
            return {}

    def _calculate_difficulty(self, caniscrape_result: dict, wafw00f_result: dict) -> int:
        """0-10 difficulty. Optional base from caniscrape score_card, then heuristics."""
        difficulty = 0
        score_card = caniscrape_result.get("score_card", {})
        base = score_card.get("score")
        if isinstance(base, int):
            difficulty = base

        if wafw00f_result.get("waf_detected"):
            difficulty += 2
        if caniscrape_result.get("captcha", {}).get("captcha_detected"):
            difficulty += 2
        if caniscrape_result.get("tls", {}).get("status") == "active":
            difficulty += 1

        return max(0, min(difficulty, 10))

    def _recommend_tool(self, difficulty: int) -> str:
        if difficulty <= 3:
            return "scrapy"
        if difficulty <= 6:
            return "crawl4ai"
        return "camoufox"

    def _recommend_proxy(self, waf: str | None) -> str:
        return "residential" if waf else "datacenter"
