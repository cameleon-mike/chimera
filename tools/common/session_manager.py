"""Session persistence: guarantees the same fingerprint + proxy for a given session_id.

Backed by Redis with a configurable TTL (default 30 min). If Redis is
unavailable, callers fall back to per-request random selection — no crash.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from network.fingerprints.loader import FingerprintLoader
    from network.proxy_pool.rotator import ProxyRotator


class SessionManager:
    _KEY_FP = "chimera:session:fp:{sid}"
    _KEY_PROXY = "chimera:session:proxy:{sid}"

    def __init__(self, redis_client, ttl: int = 1800):
        self._r = redis_client
        self._ttl = ttl

    @classmethod
    def from_url(cls, redis_url: str, ttl: int = 1800) -> "SessionManager":
        import redis
        return cls(redis.Redis.from_url(redis_url, decode_responses=True), ttl)

    @classmethod
    def from_settings(cls, settings) -> "SessionManager | None":
        """Build from Scrapy settings. Returns None if SESSION_REDIS_URL is unset."""
        url = settings.get("SESSION_REDIS_URL")
        if not url:
            return None
        try:
            return cls.from_url(url, ttl=settings.getint("SESSION_TTL", 1800))
        except Exception as exc:
            _log.warning("SessionManager init failed (SESSION_REDIS_URL=%r): %s", url, exc)
            return None

    def get_or_create_fingerprint(
        self,
        session_id: str,
        loader: "FingerprintLoader",
        geo_id: str | None = None,
    ) -> dict:
        """Return the persisted fingerprint for *session_id*, creating one if absent."""
        key = self._KEY_FP.format(sid=session_id)
        raw = self._r.get(key)
        if raw:
            return json.loads(raw)
        fp = loader.pick_coherent(geo_id=geo_id)
        self._r.setex(key, self._ttl, json.dumps(fp))
        return fp

    def get_or_create_proxy(
        self,
        session_id: str,
        rotator: "ProxyRotator",
        host: str,
    ) -> str | None:
        """Return the persisted proxy URL for *session_id*, picking one if absent.

        Returns None when the rotator has no proxy for *host*.
        """
        key = self._KEY_PROXY.format(sid=session_id)
        raw = self._r.get(key)
        if raw:
            return raw
        proxy = rotator.pick(host)
        if proxy:
            self._r.setex(key, self._ttl, proxy["url"])
            return proxy["url"]
        return None
