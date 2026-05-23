"""Scrapy downloader middleware: rotate User-Agent + headers from fingerprint pool."""
from __future__ import annotations

import random
from pathlib import Path

from network.fingerprints.loader import FingerprintLoader


# ---------------------------------------------------------------------------
# Backward-compat fallback pool (used by RotateUserAgentMiddleware below)
# ---------------------------------------------------------------------------

_FALLBACK_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
]


try:
    from fake_useragent import UserAgent as _UA
    _ua_gen = _UA()

    def _pick_ua() -> str:
        try:
            return _ua_gen.random
        except Exception:
            return random.choice(_FALLBACK_UAS)
except Exception:
    def _pick_ua() -> str:
        return random.choice(_FALLBACK_UAS)


class RotateUserAgentMiddleware:
    """Legacy middleware: sets a random UA on every outgoing request unless one is already set."""

    def process_request(self, request, spider):
        if request.headers.get("User-Agent"):
            return None
        request.headers["User-Agent"] = _pick_ua()
        return None


# ---------------------------------------------------------------------------
# New fingerprint-coherent middleware
# ---------------------------------------------------------------------------


class RotateUAMiddleware:
    def __init__(
        self,
        fingerprints_dir: str,
        geo_id: str | None,
        session_id: str | None = None,
        session_mgr=None,
    ):
        self.loader = FingerprintLoader(fingerprints_dir=Path(fingerprints_dir))
        self.geo_id = geo_id or None
        self._session_id = session_id or None
        self._session_mgr = session_mgr

    @classmethod
    def from_crawler(cls, crawler):
        from tools.common.session_manager import SessionManager
        return cls(
            fingerprints_dir=crawler.settings.get(
                "FINGERPRINTS_DIR",
                str(Path(__file__).parent.parent.parent.parent.parent / "network" / "fingerprints"),
            ),
            geo_id=crawler.settings.get("GEO_ID"),
            session_id=crawler.settings.get("SESSION_ID"),
            session_mgr=SessionManager.from_settings(crawler.settings),
        )

    def process_request(self, request, spider):
        session_id = request.meta.get("session_id") or self._session_id
        if session_id and self._session_mgr:
            fp = self._session_mgr.get_or_create_fingerprint(
                session_id, self.loader, self.geo_id
            )
        else:
            fp = self.loader.pick_coherent(geo_id=self.geo_id)

        request.headers.clear()
        for h in fp["header_order"]:
            if h in fp["headers"]:
                request.headers[h] = fp["headers"][h]
        request.headers["User-Agent"] = fp["ua"]
        request.meta["fingerprint_profile"] = fp["profile_id"]
