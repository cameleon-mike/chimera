"""DeuxememainSpider — 2ememain.be classified ads scraper.

On HTTP 403/429/503 or captcha detection, the spider sets _blocked=True
and yields no items. The bridge endpoint reports blocked=True so
SecondPulse can handle accordingly.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote_plus, urlencode

import scrapy


_BLOCK_STATUSES = {403, 429, 503}


class DeuxememainSpider(scrapy.Spider):
    name = "2ememain"
    BASE = "https://www.2ememain.be"
    PER_PAGE = 30

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.5,
        "DOWNLOAD_TIMEOUT": 30,
        "AUTOTHROTTLE_ENABLED": False,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-BE,fr;q=0.9,nl-BE;q=0.8,en;q=0.7",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        },
    }

    def __init__(
        self,
        urls=None,      # ignoré — spider construit ses propres URLs
        headers=None,   # ignoré
        job_id: str | None = None,
        q: str = "",
        max_pages: int = 3,
        **kw,
    ):
        super().__init__(**kw)
        self.q = q
        self.max_pages = int(max_pages)
        self.job_id = job_id
        self._blocked = False

    def _build_url(self, page: int) -> str:
        params = urlencode({"pp": self.PER_PAGE, "currentPage": page})
        return f"{self.BASE}/q/{quote_plus(self.q)}/?{params}"

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
            self.logger.warning("2ememain_blocked status=%d url=%s", response.status, response.url)
            return

        body_lower = response.text.lower()
        if "captcha" in body_lower or "robot check" in body_lower:
            self._blocked = True
            self.logger.warning("2ememain_captcha_detected url=%s", response.url)
            return

        page = response.meta.get("page", 1)
        items_found = 0

        # Primary: hz-Listing elements (Marktplaats/2ememain platform)
        for el in response.css("article.hz-Listing, li.hz-Listing"):
            item = self._parse_listing(el)
            if item:
                items_found += 1
                yield item

        # Fallback: article[data-item-id] (older platform version)
        if items_found == 0:
            for el in response.css("article[data-item-id]"):
                item = self._parse_listing(el)
                if item:
                    items_found += 1
                    yield item

        # Pagination
        if items_found > 0 and page < self.max_pages:
            yield scrapy.Request(
                url=self._build_url(page + 1),
                callback=self.parse,
                errback=self.handle_error,
                meta={"page": page + 1},
                dont_filter=True,
            )

    def _parse_listing(self, el) -> dict | None:
        # Cover link
        link_el = el.css("a.hz-Listing-coverLink, a[class*='coverLink'], a[href*='/a/']")
        if not link_el:
            link_el = el.css("a[href]")

        href = ""
        if link_el:
            href = link_el.attrib.get("href", "")
            if href and not href.startswith("http"):
                href = self.BASE + href

        # Title
        title = (
            el.css("h3.hz-Listing-title::text, h2.hz-Listing-title::text").get()
            or el.css("[class*='title']::text").get()
            or el.css("h2::text, h3::text").get()
            or ""
        ).strip()

        if not title and not href:
            return None

        # Price
        price_text = (
            el.css("p.hz-Listing-price *::text, p.hz-Listing-price::text").get()
            or el.css("[class*='price']::text, [class*='Price']::text").get()
            or ""
        ).strip()
        price = _parse_price_be(price_text)

        # Location
        location = (
            el.css("span.hz-Listing-location::text, [class*='location']::text").get() or ""
        ).strip() or None

        # Publication date
        date_text = (
            el.css("span.hz-Listing-date::text, [class*='date']::text").get()
            or el.css("time").attrib.get("datetime", "")
            or el.css("time::text").get()
            or ""
        ).strip()
        pub_date = _normalize_date_be(date_text)

        # Photo
        img = el.css("img[src]")
        photo_url = img.attrib.get("src") or img.attrib.get("data-src") or None
        if photo_url and photo_url.startswith("//"):
            photo_url = "https:" + photo_url
        if photo_url and photo_url.startswith("data:"):
            photo_url = None

        return {
            "title": title or None,
            "price": price,
            "start_date": pub_date,
            "end_date": None,
            "photo_url": photo_url,
            "link": href or None,
            "location": location,
            "source": "2ememain",
        }

    def handle_error(self, failure):
        status = (
            getattr(failure.value, "response", None)
            and failure.value.response.status
            or 0
        )
        self._final_http_status = status
        if status in _BLOCK_STATUSES:
            self._blocked = True
        self.logger.error("2ememain_request_failed: %s", repr(failure.value))


# ---------------------------------------------------------------------------
# Helpers (module-level so tests can import them directly)
# ---------------------------------------------------------------------------


def _parse_price_be(text: str) -> dict | None:
    """Parse Belgian/Dutch price format to {'value': float, 'currency': 'EUR'}.

    Handles: '€ 350,00', '1.234,56 €', 'EUR 25', '350'.
    Returns None for non-numeric strings ('À débattre', 'Gratis', etc.).
    """
    if not text:
        return None
    text_lower = text.lower()
    for skip in ("aanvraag", "débattre", "debattre", "gratuit", "gratis", "à conv", "sur dem", "op verz"):
        if skip in text_lower:
            return None

    # Strip currency symbols and whitespace
    cleaned = re.sub(r"[€EUReur\s]", "", text)

    # Belgian thousands separator is period; decimal is comma: "1.234,56"
    if re.search(r"\d\.\d{3}(?:[,\s]|$)", cleaned):
        cleaned = cleaned.replace(".", "")
    cleaned = cleaned.replace(",", ".")

    m = re.search(r"\d+\.?\d*", cleaned)
    if m:
        try:
            return {"value": float(m.group()), "currency": "EUR"}
        except ValueError:
            return None
    return None


def _normalize_date_be(text: str) -> str | None:
    """Normalize 2ememain date text to YYYY-MM-DD.

    Handles: "Aujourd'hui", "Hier", "Vandaag", "Gisteren",
             "dd/mm/yyyy", "dd-mm-yyyy", ISO datetime strings.
    """
    if not text:
        return None
    t = text.strip().lower()
    today = date.today()

    if any(w in t for w in ("aujourd", "today", "vandaag")):
        return today.strftime("%Y-%m-%d")
    if any(w in t for w in ("hier", "yesterday", "gisteren")):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # dd/mm/yyyy or dd-mm-yyyy
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", t)
    if m:
        d_val, mo_val, yr_val = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr_val < 100:
            yr_val += 2000
        try:
            return date(yr_val, mo_val, d_val).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # ISO date or datetime prefix (YYYY-MM-DD...)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None
