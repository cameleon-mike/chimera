"""adaptive spider — generic HTML scraping driven by CSS selectors from the
job config. config["selectors"] is a dict of {field_name: css_expression}.
config["item_selector"] (optional) selects repeating blocks; without it the
spider returns one item per URL."""

from __future__ import annotations

from datetime import UTC, datetime

import scrapy


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class AdaptiveSpider(scrapy.Spider):
    name = "adaptive"

    def __init__(
        self,
        urls: list[str] | None = None,
        selectors: dict | None = None,
        item_selector: str | None = None,
        headers: dict | None = None,
        **kw,
    ):
        super().__init__(**kw)
        self.start_urls = urls or []
        self.selectors = selectors or {}
        self.item_selector = item_selector
        self.extra_headers = headers or {}

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url, headers=self.extra_headers,
                callback=self.parse, errback=self.errback,
                dont_filter=True,
            )

    def _extract_one(self, sel, url) -> dict:
        record = {"url": url, "fetched_at": _iso_now()}
        for field, css in self.selectors.items():
            value = sel.css(css).getall()
            record[field] = value[0] if len(value) == 1 else value
        return record

    def parse(self, response):
        self._final_http_status = response.status
        if self.item_selector:
            for block in response.css(self.item_selector):
                yield self._extract_one(block, response.url)
        else:
            yield self._extract_one(response, response.url)

    def errback(self, failure):
        self._final_http_status = (
            getattr(failure.value, "response", None) and failure.value.response.status or 0
        )
        yield {
            "url": failure.request.url,
            "fetched_at": _iso_now(),
            "error": repr(failure.value),
        }
