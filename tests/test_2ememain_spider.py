"""Tests pour DeuxememainSpider et ses helpers."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from scrapy.http import TextResponse, Request

from tools.scrapy_runner.project.spiders.vinted_2ememain import (
    DeuxememainSpider,
    _normalize_date_be,
    _parse_price_be,
)


# ---------------------------------------------------------------------------
# _parse_price_be unit tests
# ---------------------------------------------------------------------------


def test_price_standard_be():
    """'€ 350,00' → {value: 350.0, currency: 'EUR'}."""
    r = _parse_price_be("€ 350,00")
    assert r == {"value": 350.0, "currency": "EUR"}


def test_price_thousands_separator():
    """'1.234,56 €' → 1234.56."""
    r = _parse_price_be("1.234,56 €")
    assert r is not None
    assert r["value"] == pytest.approx(1234.56, abs=0.01)
    assert r["currency"] == "EUR"


def test_price_no_decimal():
    """'EUR 25' → 25.0."""
    r = _parse_price_be("EUR 25")
    assert r is not None
    assert r["value"] == pytest.approx(25.0)


def test_price_plain_number():
    """'350' (sans symbole) → 350.0 EUR."""
    r = _parse_price_be("350")
    assert r is not None
    assert r["value"] == pytest.approx(350.0)


def test_price_gratis():
    """'Gratis' → None."""
    assert _parse_price_be("Gratis") is None


def test_price_gratuit():
    """'Gratuit' → None."""
    assert _parse_price_be("Gratuit") is None


def test_price_a_debattre():
    """'À débattre' → None."""
    assert _parse_price_be("À débattre") is None


def test_price_op_aanvraag():
    """'Op aanvraag' (sur demande NL) → None."""
    assert _parse_price_be("Op aanvraag") is None


def test_price_empty():
    assert _parse_price_be("") is None


# ---------------------------------------------------------------------------
# _normalize_date_be unit tests
# ---------------------------------------------------------------------------


def test_date_today_fr():
    """'Aujourd'hui' → today."""
    result = _normalize_date_be("Aujourd'hui")
    assert result == date.today().strftime("%Y-%m-%d")


def test_date_today_nl():
    """'Vandaag' → today."""
    result = _normalize_date_be("Vandaag")
    assert result == date.today().strftime("%Y-%m-%d")


def test_date_yesterday_fr():
    """'Hier' → yesterday."""
    result = _normalize_date_be("Hier")
    expected = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert result == expected


def test_date_yesterday_nl():
    """'Gisteren' → yesterday."""
    result = _normalize_date_be("Gisteren")
    expected = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert result == expected


def test_date_dd_mm_yyyy():
    """'14/05/2026' → '2026-05-14'."""
    assert _normalize_date_be("14/05/2026") == "2026-05-14"


def test_date_dd_mm_yyyy_dash():
    """'14-05-2026' → '2026-05-14'."""
    assert _normalize_date_be("14-05-2026") == "2026-05-14"


def test_date_iso():
    """ISO datetime string '2026-05-14T10:30:00' → '2026-05-14'."""
    assert _normalize_date_be("2026-05-14T10:30:00") == "2026-05-14"


def test_date_empty():
    assert _normalize_date_be("") is None


def test_date_unknown_text():
    """Texte non reconnu → None."""
    assert _normalize_date_be("Binnenkort") is None


# ---------------------------------------------------------------------------
# Spider instantiation
# ---------------------------------------------------------------------------


def make_spider(**kwargs) -> DeuxememainSpider:
    return DeuxememainSpider(q="wacom cintiq", **kwargs)


def test_spider_default_not_blocked():
    spider = make_spider()
    assert spider._blocked is False


def test_spider_name():
    assert DeuxememainSpider.name == "2ememain"


def test_spider_build_url_page1():
    """Page 1 URL contient le query encodé."""
    spider = make_spider()
    url = spider._build_url(1)
    assert "wacom" in url
    assert "2ememain.be" in url


def test_spider_build_url_page2():
    """Page 2 URL contient currentPage=2."""
    spider = make_spider()
    url = spider._build_url(2)
    assert "currentPage=2" in url


def test_spider_max_pages_default():
    spider = DeuxememainSpider(q="test")
    assert spider.max_pages == 3


def test_spider_max_pages_override():
    spider = DeuxememainSpider(q="test", max_pages=5)
    assert spider.max_pages == 5


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def make_response(body: str, url: str = "https://www.2ememain.be/q/wacom/?pp=30&currentPage=1") -> TextResponse:
    req = Request(url=url)
    return TextResponse(url=url, body=body.encode("utf-8"), encoding="utf-8", request=req)


SAMPLE_HTML = """
<html><body>
<ul class="hz-Listings">
  <li class="hz-Listing">
    <article>
      <a class="hz-Listing-coverLink" href="/a/pc-mac-en-software/wacom-cintiq-16/12345678.html">
        <figure class="hz-Listing-image">
          <img src="https://images.2dehands.be/api/image/12345678.jpg" />
        </figure>
        <h3 class="hz-Listing-title">Wacom Cintiq 16</h3>
        <p class="hz-Listing-price"><strong>€ 350,00</strong></p>
        <span class="hz-Listing-location">Bruxelles</span>
        <span class="hz-Listing-date">Aujourd'hui</span>
      </a>
    </article>
  </li>
  <li class="hz-Listing">
    <article>
      <a class="hz-Listing-coverLink" href="/a/pc-mac-en-software/intuos-pro/98765432.html">
        <h3 class="hz-Listing-title">Wacom Intuos Pro M</h3>
        <p class="hz-Listing-price"><strong>€ 120,00</strong></p>
        <span class="hz-Listing-location">Gent</span>
        <span class="hz-Listing-date">Hier</span>
      </a>
    </article>
  </li>
</ul>
</body></html>
"""

BLOCKED_403_HTML = "<html><body><h1>Access Denied</h1></body></html>"
CAPTCHA_HTML = "<html><body><p>Please complete the captcha to verify you are human.</p></body></html>"


def parse_items_only(spider, resp) -> list[dict]:
    """Filter only item dicts from spider.parse() (excludes pagination Requests)."""
    import scrapy
    return [x for x in spider.parse(resp) if isinstance(x, dict)]


def test_parse_items_from_html():
    """Spider parse correctement 2 items depuis le HTML hz-Listing."""
    spider = make_spider()
    resp = make_response(SAMPLE_HTML)
    items = parse_items_only(spider, resp)
    assert len(items) == 2


def test_parse_first_item_fields():
    """Premier item contient tous les champs attendus."""
    spider = make_spider()
    resp = make_response(SAMPLE_HTML)
    items = parse_items_only(spider, resp)
    first = items[0]
    assert first["title"] == "Wacom Cintiq 16"
    assert first["price"] == {"value": 350.0, "currency": "EUR"}
    assert first["location"] == "Bruxelles"
    assert first["start_date"] == date.today().strftime("%Y-%m-%d")
    assert first["end_date"] is None
    assert first["source"] == "2ememain"
    assert "2ememain.be" in first["link"]
    assert "jpg" in first["photo_url"]


def test_parse_second_item_yesterday():
    """Deuxième item a start_date = hier."""
    spider = make_spider()
    resp = make_response(SAMPLE_HTML)
    items = parse_items_only(spider, resp)
    expected = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert items[1]["start_date"] == expected


def test_parse_all_items_source():
    """Tous les items ont source='2ememain'."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    assert all(i["source"] == "2ememain" for i in items)


def test_parse_captcha_detected():
    """Page captcha → _blocked=True, aucun item."""
    spider = make_spider()
    resp = make_response(CAPTCHA_HTML)
    items = list(spider.parse(resp))
    assert items == []
    assert spider._blocked is True


def test_parse_blocked_status():
    """HTTP 403 → _blocked=True, aucun item."""
    spider = make_spider()
    req = Request(url="https://www.2ememain.be/q/wacom/?pp=30&currentPage=1")
    resp = TextResponse(
        url="https://www.2ememain.be/q/wacom/?pp=30&currentPage=1",
        body=BLOCKED_403_HTML.encode(),
        status=403,
        encoding="utf-8",
        request=req,
    )
    items = list(spider.parse(resp))
    assert items == []
    assert spider._blocked is True


def test_parse_empty_page():
    """Page sans listings → liste vide, pas de crash."""
    spider = make_spider()
    resp = make_response("<html><body><p>Aucun résultat</p></body></html>")
    items = parse_items_only(spider, resp)
    assert items == []
    assert spider._blocked is False


def test_parse_link_absolute():
    """Les liens relatifs sont convertis en URLs absolues."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    for item in items:
        assert item["link"].startswith("https://www.2ememain.be")


def test_fallback_selector_data_item_id():
    """Fallback article[data-item-id] quand hz-Listing absent."""
    html = """
    <html><body>
    <article data-item-id="999">
      <a href="/a/item/999.html">
        <h3>Fallback item</h3>
        <p class="price">€ 75,00</p>
      </a>
    </article>
    </body></html>
    """
    spider = make_spider()
    items = parse_items_only(spider, make_response(html))
    assert len(items) == 1
    assert items[0]["title"] == "Fallback item"
