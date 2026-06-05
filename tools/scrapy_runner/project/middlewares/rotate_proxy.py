"""Scrapy downloader middleware: proxy rotation via ProxyRotator.

Activated only when PROXY_TIER is set in Scrapy settings.
Noop otherwise — existing S1 tests are unaffected.
"""
from __future__ import annotations

from scrapy import Spider
from scrapy.http import Request, Response


class RotateProxyMiddleware:
    def __init__(self, rotator, session_id: str | None = None, session_mgr=None):
        self._rotator = rotator
        self._session_id = session_id or None
        self._session_mgr = session_mgr

    @classmethod
    def from_crawler(cls, crawler):
        """Instantiate only if PROXY_TIER is configured."""
        tier = crawler.settings.get("PROXY_TIER")
        if not tier:
            return cls(rotator=None)
        from pathlib import Path
        from network.proxy_pool.rotator import ProxyRotator
        from tools.common.session_manager import SessionManager
        pool_file = Path(__file__).parents[5] / "network/proxy_pool/pool.json"
        rotator = ProxyRotator(pool_file=pool_file, tier=tier)
        return cls(
            rotator=rotator,
            session_id=crawler.settings.get("SESSION_ID"),
            session_mgr=SessionManager.from_settings(crawler.settings),
        )

    def process_request(self, request: Request, spider: Spider):
        if self._rotator is None:
            return None
        host = request.url.split("/")[2]
        session_id = request.meta.get("session_id") or self._session_id
        if session_id and self._session_mgr:
            proxy_url = self._session_mgr.get_or_create_proxy(
                session_id, self._rotator, host
            )
        else:
            proxy = self._rotator.pick(host)
            proxy_url = proxy["url"] if proxy else None
        if proxy_url:
            request.meta["proxy"] = proxy_url
            request.meta["dont_verify_ssl"] = True
        return None

    def process_response(self, request: Request, response: Response, spider: Spider):
        if self._rotator is None:
            return response
        proxy_url = request.meta.get("proxy")
        if proxy_url:
            host = request.url.split("/")[2]
            self._rotator.report(proxy_url, host, response.status)
        return response
