"""EbayBrowseSpider — eBay Browse API v1, pagination, OAuth2, rotation de clés."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import scrapy

from tools.scrapy_runner.ebay_auth import EbayTokenManager


class EbayBrowseSpider(scrapy.Spider):
    name = "ebay_browse"

    API_BASE = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    # Override settings pour l'API (pas un site web)
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 0,
        "AUTOTHROTTLE_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 30,
        # Désactiver la rotation UA : elle efface headers.clear() → perd Authorization
        "DOWNLOADER_MIDDLEWARES": {
            "tools.scrapy_runner.project.middlewares.rotate_ua.RotateUAMiddleware": None,
            "tools.scrapy_runner.project.middlewares.rotate_ua.RotateUserAgentMiddleware": None,
        },
    }

    def __init__(
        self,
        urls=None,           # ignoré — l'API construit ses propres URLs
        headers=None,        # ignoré — auth Bearer gérée en interne
        job_id=None,
        q: str = "",
        marketplace_id: str = "EBAY_FR",
        max_pages: int = 3,
        ebay_app_ids=None,   # list[str]
        ebay_cert_ids=None,  # list[str]
        **kw,
    ):
        super().__init__(**kw)
        self.q = q
        self.marketplace_id = marketplace_id
        self.max_pages = int(max_pages)
        self.job_id = job_id

        app_ids = list(ebay_app_ids) if ebay_app_ids else []
        cert_ids = list(ebay_cert_ids) if ebay_cert_ids else []

        self._token_manager = EbayTokenManager(app_ids, cert_ids)
        self._key_index = self._token_manager.pick_key()
        self._page_count = 0
        # Ne PAS initialiser _collected_items ni _final_http_status (fait par CollectorPipeline)

    async def start(self):
        try:
            token = self._token_manager.get_token(self._key_index)
            self._token_manager.record_call(self._key_index)
        except Exception as exc:
            self.logger.error("ebay_auth_failed: %s", repr(exc))
            return

        url = self._build_url(offset=0)
        yield scrapy.Request(
            url=url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
                "Content-Type": "application/json",
            },
            callback=self.parse_items,
            errback=self.handle_error,
            meta={"page": 0, "token": token},
            dont_filter=True,
        )

    def _build_url(self, offset: int) -> str:
        params = urlencode({
            "q": self.q,
            "limit": 200,
            "offset": offset,
            "filter": "conditions:{USED}",
        })
        return f"{self.API_BASE}?{params}"

    def parse_items(self, response):
        self._final_http_status = response.status

        try:
            data = response.json()
        except Exception as exc:
            self.logger.error("ebay_json_parse_failed: %s", repr(exc))
            return

        # Vérifie erreur 10001 (quota/auth) → rotation de clé, retry
        errors = data.get("errors", [])
        if any(e.get("errorId") == 10001 for e in errors):
            try:
                new_index = self._token_manager.pick_key()
            except KeyError:
                self.logger.error("ebay_all_keys_exhausted")
                return
            self._key_index = new_index
            try:
                new_token = self._token_manager.get_token(new_index)
                self._token_manager.record_call(new_index)
            except Exception as exc:
                self.logger.error("ebay_auth_rotation_failed: %s", repr(exc))
                return
            page = response.meta["page"]
            offset = page * 200
            retry_url = self._build_url(offset=offset)
            yield scrapy.Request(
                url=retry_url,
                headers={
                    "Authorization": f"Bearer {new_token}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
                    "Content-Type": "application/json",
                },
                callback=self.parse_items,
                errback=self.handle_error,
                meta={"page": page, "token": new_token},
                dont_filter=True,
            )
            return

        page = response.meta["page"]
        token = response.meta["token"]

        for raw_item in data.get("itemSummaries", []):
            yield self._parse_item(raw_item)

        # Pagination
        total = data.get("total", 0)
        next_page = page + 1
        next_offset = next_page * 200

        if next_page < self.max_pages and next_offset < total:
            next_url = self._build_url(offset=next_offset)
            try:
                next_token = self._token_manager.get_token(self._key_index)
                self._token_manager.record_call(self._key_index)
            except Exception as exc:
                self.logger.error("ebay_token_refresh_failed: %s", repr(exc))
                return
            yield scrapy.Request(
                url=next_url,
                headers={
                    "Authorization": f"Bearer {next_token}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
                    "Content-Type": "application/json",
                },
                callback=self.parse_items,
                errback=self.handle_error,
                meta={"page": next_page, "token": next_token},
                dont_filter=True,
            )

    def _parse_item(self, raw: dict) -> dict:
        price_raw = raw.get("price", {})
        try:
            price_value = float(price_raw.get("value")) if price_raw.get("value") is not None else None
        except (TypeError, ValueError):
            price_value = None

        start_raw = raw.get("itemCreationDate")
        start_date = start_raw[:10] if start_raw else None

        end_raw = raw.get("itemEndDate")
        end_date = end_raw[:10] if end_raw else None

        image = raw.get("image", {}) or {}
        photo_url = image.get("imageUrl")

        return {
            "title": raw.get("title"),
            "price": {
                "value": price_value,
                "currency": price_raw.get("currency") if price_raw else None,
            },
            "epid": raw.get("epid"),
            "start_date": start_date,
            "end_date": end_date,
            "photo_url": photo_url,
            "link": raw.get("itemWebUrl"),
        }

    def handle_error(self, failure):
        self._final_http_status = (
            getattr(failure.value, "response", None) and failure.value.response.status or 0
        )
        self.logger.error("ebay_request_failed: %s", repr(failure.value))
