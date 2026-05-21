"""Per-request User-Agent rotation.

Uses `fake-useragent` (already in pyproject deps) with a hardcoded fallback
pool of 5 modern UAs so the runner keeps working offline (fake-useragent
fetches from a remote dataset on first use). Real fingerprint coherence
arrives in Session 2 (Step 2.2)."""

from __future__ import annotations

import random

try:
    from fake_useragent import UserAgent
    _ua = UserAgent()
    def _pick_ua() -> str:
        try:
            return _ua.random
        except Exception:
            return random.choice(_FALLBACK_UAS)
except Exception:
    def _pick_ua() -> str:
        return random.choice(_FALLBACK_UAS)


_FALLBACK_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
]


class RotateUserAgentMiddleware:
    """Sets a random UA on every outgoing request unless one is already set."""

    def process_request(self, request, spider):
        if request.headers.get("User-Agent"):
            return None
        request.headers["User-Agent"] = _pick_ua()
        return None
