"""api_json spider — fetches one or many JSON endpoints and stores the parsed
body verbatim in `data`. Suited to public APIs (httpbin, REST endpoints)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import scrapy


class ApiJsonSpider(scrapy.Spider):
    name = "api_json"

    def __init__(self, urls: list[str] | None = None, headers: dict | None = None, **kw):
        super().__init__(**kw)
        self.start_urls = urls or []
        self.extra_headers = headers or {}

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                headers=self.extra_headers,
                callback=self.parse,
                errback=self.errback,
                dont_filter=True,
            )

    def parse(self, response):
        self._final_http_status = response.status
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            data = {"_raw": response.text[:10_000], "_parse_error": "not_json"}
        yield {
            "url": response.url,
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "http_status": response.status,
            "data": data,
        }

    def errback(self, failure):
        # Surface failures into the result rather than silently dropping.
        self._final_http_status = getattr(failure.value, "response", None) and failure.value.response.status or 0
        yield {
            "url": failure.request.url,
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "http_status": self._final_http_status,
            "data": None,
            "error": repr(failure.value),
        }
