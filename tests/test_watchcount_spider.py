"""Tests pour WatchCountSpider et ses helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from scrapy.http import TextResponse, Request

from tools.scrapy_runner.project.spiders.watchcount import (
    WatchCountSpider,
    _parse_remaining,
    _parse_int,
    _parse_price,
    _extract_item_id,
    MARKETPLACE_TO_LANG,
)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_parse_remaining_days_and_hours():
    """'2d 14h' doit produire une date ~2j14h dans le futur."""
    result = _parse_remaining("2d 14h")
    assert result is not None
    # Vérifie que la date est dans ~2-3 jours
    parsed = datetime.strptime(result, "%Y-%m-%d")
    delta = (parsed.date() - datetime.now(timezone.utc).date()).days
    assert 2 <= delta <= 3


def test_parse_remaining_hours_only():
    """'5h 30m' → date aujourd'hui ou demain."""
    result = _parse_remaining("5h 30m")
    assert result is not None
    parsed = datetime.strptime(result, "%Y-%m-%d")
    delta = (parsed.date() - datetime.now(timezone.utc).date()).days
    assert 0 <= delta <= 1


def test_parse_remaining_days_only():
    """'10d' → ~10 jours dans le futur."""
    result = _parse_remaining("10d")
    assert result is not None
    parsed = datetime.strptime(result, "%Y-%m-%d")
    delta = (parsed.date() - datetime.now(timezone.utc).date()).days
    assert 9 <= delta <= 11


def test_parse_remaining_empty():
    """Chaîne vide → None."""
    assert _parse_remaining("") is None


def test_parse_remaining_no_units():
    """Texte sans unités reconnues → None."""
    assert _parse_remaining("Ended") is None
    assert _parse_remaining("Sold") is None


def test_parse_int_plain():
    assert _parse_int("458") == 458


def test_parse_int_with_commas():
    """'1,234' → 1234."""
    assert _parse_int("1,234") == 1234


def test_parse_int_empty():
    assert _parse_int("") is None


def test_parse_int_no_digits():
    assert _parse_int("N/A") is None


def test_parse_price_eur():
    """'€349.99' → 349.99."""
    assert _parse_price("€349.99") == 349.99


def test_parse_price_with_currency_text():
    """'EUR 250.00' → 250.0."""
    assert _parse_price("EUR 250.00") == 250.0


def test_parse_price_comma_decimal():
    """'199,99' → 199.99."""
    result = _parse_price("199,99")
    assert result == pytest.approx(199.99, abs=0.01)


def test_parse_price_empty():
    assert _parse_price("") is None


def test_extract_item_id_standard():
    """URL standard /itm/123456789012 → '123456789012'."""
    url = "https://www.ebay.fr/itm/123456789012"
    assert _extract_item_id(url) == "123456789012"


def test_extract_item_id_with_slug():
    """URL avec slug /itm/wacom-cintiq/123456789012 → '123456789012'."""
    url = "https://www.ebay.fr/itm/wacom-cintiq/123456789012"
    assert _extract_item_id(url) == "123456789012"


def test_extract_item_id_no_url():
    assert _extract_item_id("") is None
    assert _extract_item_id(None) is None


def test_marketplace_lang_mapping():
    """Tous les marketplaces principaux ont un mapping lang."""
    for mkt in ("EBAY_FR", "EBAY_DE", "EBAY_GB", "EBAY_BE", "EBAY_NL"):
        assert mkt in MARKETPLACE_TO_LANG


# ---------------------------------------------------------------------------
# Spider instantiation
# ---------------------------------------------------------------------------


def make_spider(**kwargs) -> WatchCountSpider:
    return WatchCountSpider(q="wacom cintiq", marketplace="EBAY_FR", **kwargs)


def test_spider_start_url_contains_query():
    """L'URL construite contient le query encodé."""
    spider = make_spider()
    assert "wacom" in spider._start_url
    assert "cintiq" in spider._start_url


def test_spider_marketplace_lang():
    """EBAY_DE → lang=de dans l'URL."""
    spider = WatchCountSpider(q="test", marketplace="EBAY_DE")
    assert "lang=de" in spider._start_url


def test_spider_default_no_recaptcha():
    """Spider créé sans reCAPTCHA → flag à False."""
    spider = make_spider()
    assert spider._recaptcha_detected is False


# ---------------------------------------------------------------------------
# Parsing HTML responses
# ---------------------------------------------------------------------------


def make_response(body: str, url: str = "https://www.watchcount.com/listing.cgi?lang=fr&q=wacom") -> TextResponse:
    req = Request(url=url)
    return TextResponse(url=url, body=body.encode("utf-8"), encoding="utf-8", request=req)


SAMPLE_HTML = """
<html><body>
<table>
<tr class="r">
  <td>1</td>
  <td>458</td>
  <td>2d 14h</td>
  <td>€349.99</td>
  <td><a href="https://www.ebay.fr/itm/123456789012" title="Wacom Cintiq 16">Wacom Cintiq 16</a></td>
</tr>
<tr class="r">
  <td>2</td>
  <td>210</td>
  <td>5h 30m</td>
  <td>€199.00</td>
  <td><a href="https://www.ebay.fr/itm/987654321098" title="Wacom Intuos Pro">Wacom Intuos Pro</a></td>
</tr>
</table>
</body></html>
"""

RECAPTCHA_HTML = """
<html><body>
<div class="g-recaptcha" data-sitekey="xxx"></div>
<p>Please complete the captcha to continue.</p>
</body></html>
"""


def test_parse_items_from_html():
    """Spider parse correctement 2 items depuis le HTML."""
    spider = make_spider()
    resp = make_response(SAMPLE_HTML)
    items = list(spider.parse(resp))
    assert len(items) == 2
    assert items[0]["title"] == "Wacom Cintiq 16"
    assert items[0]["watch_count"] == 458
    assert items[0]["ebay_item_id"] == "123456789012"
    assert items[0]["price"] == pytest.approx(349.99, abs=0.01)
    assert items[0]["end_date"] is not None


def test_parse_recaptcha_detected():
    """Réponse avec g-recaptcha → _recaptcha_detected=True, aucun item."""
    spider = make_spider()
    resp = make_response(RECAPTCHA_HTML)
    items = list(spider.parse(resp))
    assert items == []
    assert spider._recaptcha_detected is True


def test_parse_empty_table():
    """Table vide → liste vide, pas de crash."""
    spider = make_spider()
    resp = make_response("<html><body><table></table></body></html>")
    items = list(spider.parse(resp))
    assert items == []
    assert spider._recaptcha_detected is False


def test_parse_item_source_field():
    """Chaque item a source='watchcount'."""
    spider = make_spider()
    resp = make_response(SAMPLE_HTML)
    items = list(spider.parse(resp))
    assert all(i["source"] == "watchcount" for i in items)
