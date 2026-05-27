"""WatchCountSpider — scrapes watchcount.com for eBay listing data (watch count + end date).

On reCAPTCHA detection the spider sets _recaptcha_detected=True and yields no items.
The bridge endpoint then escalates to Screenshot + Groq Vision.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import scrapy


MARKETPLACE_TO_LANG: dict[str, str] = {
    "EBAY_FR": "fr",
    "EBAY_DE": "de",
    "EBAY_GB": "gb",
    "EBAY_BE": "fr",
    "EBAY_NL": "nl",
    "EBAY_IT": "it",
    "EBAY_ES": "es",
}


class WatchCountSpider(scrapy.Spider):
    name = "watchcount"

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.5,
        "DOWNLOAD_TIMEOUT": 30,
        "AUTOTHROTTLE_ENABLED": False,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }

    def __init__(
        self,
        urls=None,      # ignored — spider builds its own URL
        headers=None,   # unused
        job_id: str | None = None,
        q: str = "",
        marketplace: str = "EBAY_FR",
        **kw,
    ):
        super().__init__(**kw)
        self.q = q
        self.marketplace = marketplace
        self.job_id = job_id
        self._recaptcha_detected = False

        lang = MARKETPLACE_TO_LANG.get(marketplace, "en")
        self._start_url = (
            "https://www.watchcount.com/listing.cgi"
            f"?lang={lang}&ldc=0&q={quote_plus(q)}&order=wc"
        )

    async def start(self):
        yield scrapy.Request(
            url=self._start_url,
            callback=self.parse,
            errback=self.handle_error,
            dont_filter=True,
        )

    def parse(self, response):
        self._final_http_status = response.status

        body = response.text.lower()
        if "g-recaptcha" in body or "recaptcha" in body:
            self._recaptcha_detected = True
            self.logger.warning("watchcount_recaptcha_detected url=%s", response.url)
            return

        items_found = 0

        # Primary selectors: rows with class "r", "r1" or "r2"
        for row in response.css("tr.r, tr.r1, tr.r2"):
            item = self._parse_row(row)
            if item:
                items_found += 1
                yield item

        # Fallback: any table row with ≥4 <td> children that contains an <a href> to eBay
        if items_found == 0:
            for row in response.css("table tr"):
                cells = row.css("td")
                if len(cells) < 4:
                    continue
                links = row.css("a[href*='ebay']")
                if not links:
                    continue
                item = self._parse_row_generic(cells)
                if item:
                    items_found += 1
                    yield item

    def _parse_row(self, row) -> dict | None:
        cells = row.css("td")
        if len(cells) < 4:
            return None

        link_el = row.css("a")
        title = (link_el.attrib.get("title") or link_el.css("::text").get() or "").strip()
        ebay_url = link_el.attrib.get("href", "")

        if not title and not ebay_url:
            return None

        watch_count_text = cells[1].css("::text").get("").strip()
        remaining_text = cells[2].css("::text").get("").strip()
        price_text = cells[3].css("::text").get("").strip()

        return {
            "title": title or None,
            "watch_count": _parse_int(watch_count_text),
            "end_date": _parse_remaining(remaining_text),
            "price": _parse_price(price_text),
            "ebay_url": ebay_url or None,
            "ebay_item_id": _extract_item_id(ebay_url),
            "source": "watchcount",
        }

    def _parse_row_generic(self, cells) -> dict | None:
        last_cell = cells[-1]
        link_el = last_cell.css("a")
        title = (link_el.attrib.get("title") or link_el.css("::text").get() or "").strip()
        ebay_url = link_el.attrib.get("href", "")

        if not title:
            return None

        texts = [c.css("::text").get("").strip() for c in cells]
        return {
            "title": title or None,
            "watch_count": _parse_int(texts[1]) if len(texts) > 1 else None,
            "end_date": _parse_remaining(texts[2]) if len(texts) > 2 else None,
            "price": _parse_price(texts[3]) if len(texts) > 3 else None,
            "ebay_url": ebay_url or None,
            "ebay_item_id": _extract_item_id(ebay_url),
            "source": "watchcount",
        }

    def handle_error(self, failure):
        self._final_http_status = (
            getattr(failure.value, "response", None)
            and failure.value.response.status
            or 0
        )
        self.logger.error("watchcount_request_failed: %s", repr(failure.value))


# ---------------------------------------------------------------------------
# Helpers (module-level so tests can import them directly)
# ---------------------------------------------------------------------------


def _parse_remaining(text: str) -> str | None:
    """Convert '2d 14h' or '14h 30m' to YYYY-MM-DD relative to UTC now."""
    if not text:
        return None
    total_seconds = 0
    for match in re.finditer(r"(\d+)\s*([dhms])", text.lower()):
        n, unit = int(match.group(1)), match.group(2)
        if unit == "d":
            total_seconds += n * 86400
        elif unit == "h":
            total_seconds += n * 3600
        elif unit == "m":
            total_seconds += n * 60
        elif unit == "s":
            total_seconds += n
    if total_seconds == 0:
        return None
    end = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
    return end.strftime("%Y-%m-%d")


def _parse_int(text: str) -> int | None:
    m = re.search(r"\d[\d,]*", text)
    if m:
        try:
            return int(m.group().replace(",", ""))
        except ValueError:
            return None
    return None


def _parse_price(text: str) -> float | None:
    m = re.search(r"\d+[.,]?\d*", text.replace(" ", ""))
    if m:
        try:
            return float(m.group().replace(",", "."))
        except ValueError:
            return None
    return None


def _extract_item_id(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"/itm/(?:[^/]+/)?(\d{10,})", url)
    return m.group(1) if m else None
