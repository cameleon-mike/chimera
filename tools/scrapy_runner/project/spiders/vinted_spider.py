"""VintedSpider — vinted.fr listings scraper.

On HTTP 403/429 or captcha detection, sets _blocked=True and yields no items.
Uses UniversalExtractor (CSS → LLM cascade) for robust extraction.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

import scrapy

VINTED_SCHEMA = str(Path(__file__).resolve().parents[4] / "tools/extractors/schemas/vinted_fr.json")

_BLOCK_STATUSES = {403, 429, 503}


def html_to_markdown(html: str) -> str:
    """Minimal HTML→text conversion for LLM fallback."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


class VintedSpider(scrapy.Spider):
    name = "vinted"

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 2.0,
        "DOWNLOAD_TIMEOUT": 30,
        "AUTOTHROTTLE_ENABLED": False,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        },
    }

    def __init__(
        self,
        urls=None,
        headers=None,
        job_id: str | None = None,
        q: str = "",
        marketplace: str = "FR",
        max_pages: int = 3,
        groq_api_key: str = "",
        **kw,
    ):
        super().__init__(**kw)
        self.q = q
        self.marketplace = marketplace
        self.max_pages = int(max_pages)
        self.groq_api_key = groq_api_key
        self.job_id = job_id
        self._blocked = False
        self._final_http_status = 0
        self._collected_items = []

    def _build_url(self, page: int = 1) -> str:
        return (
            f"https://www.vinted.fr/catalog"
            f"?search_text={quote_plus(self.q)}&order=newest_first&page={page}"
        )

    async def start(self):
        yield scrapy.Request(
            url=self._build_url(1),
            callback=self.parse,
            errback=self.handle_error,
            meta={"page": 1},
            dont_filter=True,
        )

    def parse(self, response):
        self._final_http_status = response.status

        if response.status in _BLOCK_STATUSES:
            self._blocked = True
            self.logger.warning("vinted_blocked status=%d url=%s", response.status, response.url)
            return

        body_lower = response.text.lower()
        if "captcha" in body_lower or "robot" in body_lower:
            self._blocked = True
            self.logger.warning("vinted_captcha_detected url=%s", response.url)
            return

        from tools.extractors.universal_extractor import UniversalExtractor
        extractor = UniversalExtractor(
            schema_path=VINTED_SCHEMA,
            groq_api_key=self.groq_api_key,
        )
        html = response.text
        markdown = html_to_markdown(html)
        items = extractor.extract(html, markdown)

        page = response.meta.get("page", 1)
        for item in items:
            item["source"] = "vinted"
            self._collected_items.append(item)
            yield item

        if items and page < self.max_pages:
            yield scrapy.Request(
                url=self._build_url(page + 1),
                callback=self.parse,
                errback=self.handle_error,
                meta={"page": page + 1},
                dont_filter=True,
            )

    def handle_error(self, failure):
        status = (
            getattr(failure.value, "response", None)
            and failure.value.response.status
            or 0
        )
        self._final_http_status = status
        if status in _BLOCK_STATUSES:
            self._blocked = True
        self.logger.error("vinted_request_failed: %s", repr(failure.value))
