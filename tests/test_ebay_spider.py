"""Tests pour EbayBrowseSpider._parse_item() et parse_items()."""
import json
import pytest
from unittest.mock import MagicMock, patch
from scrapy.http import TextResponse, Request

from tools.scrapy_runner.project.spiders.ebay_browse import EbayBrowseSpider
from tools.scrapy_runner.ebay_auth import EbayTokenManager


SAMPLE_ITEM = {
    "title": "Wacom Cintiq 16 DTK1660K",
    "price": {"value": "250.00", "currency": "EUR"},
    "epid": "12345678",
    "itemCreationDate": "2026-05-01T10:00:00Z",
    "itemEndDate": "2026-06-01T10:00:00Z",
    "image": {"imageUrl": "https://i.ebayimg.com/thumbs/images/g/abc/s-l500.jpg"},
    "itemWebUrl": "https://www.ebay.fr/itm/123456789",
}


def make_spider(**kwargs):
    """Crée un spider avec mock du EbayTokenManager."""
    with patch.object(EbayTokenManager, 'get_token', return_value='fake_tok'), \
         patch.object(EbayTokenManager, 'pick_key', return_value=0), \
         patch.object(EbayTokenManager, '_fetch_token', return_value='fake_tok'):
        return EbayBrowseSpider(
            ebay_app_ids=["app_id"],
            ebay_cert_ids=["cert_id"],
            q="wacom cintiq",
            **kwargs,
        )


def make_response(items, total=None, page=0):
    data = {"itemSummaries": items, "total": total or len(items)}
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?q=wacom&offset=0"
    req = Request(url=url)
    resp = TextResponse(url=url, body=json.dumps(data).encode(), encoding="utf-8", request=req)
    resp.request.meta["page"] = page
    resp.request.meta["token"] = "fake_tok"
    return resp


def test_parse_item_full():
    """Spider parse un item eBay correctement."""
    spider = make_spider()
    result = spider._parse_item(SAMPLE_ITEM)
    assert result["title"] == "Wacom Cintiq 16 DTK1660K"
    assert result["epid"] == "12345678"
    assert result["link"] == "https://www.ebay.fr/itm/123456789"


def test_price_extracted():
    """Prix extrait (value + currency)."""
    spider = make_spider()
    result = spider._parse_item(SAMPLE_ITEM)
    assert result["price"]["value"] == 250.0
    assert result["price"]["currency"] == "EUR"


def test_epid_present():
    """EPID présent si disponible."""
    spider = make_spider()
    result = spider._parse_item(SAMPLE_ITEM)
    assert result["epid"] == "12345678"


def test_dates_extracted():
    """Dates extraites si présentes."""
    spider = make_spider()
    result = spider._parse_item(SAMPLE_ITEM)
    assert result["start_date"] == "2026-05-01"
    assert result["end_date"] == "2026-06-01"


def test_item_url():
    """URL item correcte."""
    spider = make_spider()
    result = spider._parse_item(SAMPLE_ITEM)
    assert "ebay.fr" in result["link"]


def test_photo_url_extracted():
    """Photo URL extraite."""
    spider = make_spider()
    result = spider._parse_item(SAMPLE_ITEM)
    assert result["photo_url"] == "https://i.ebayimg.com/thumbs/images/g/abc/s-l500.jpg"


def test_pagination_max_pages():
    """Pagination: au-delà de max_pages, pas de nouvelle requête."""
    spider = make_spider(max_pages=1)
    spider._collected_items = []
    response = make_response([SAMPLE_ITEM], total=400, page=0)
    results = list(spider.parse_items(response))
    # max_pages=1 → page 0 est la seule → pas de requête suivante
    requests_yielded = [r for r in results if hasattr(r, 'url') and not isinstance(r, dict)]
    assert len(requests_yielded) == 0


def test_epid_absent_item_included():
    """Si epid absent → item inclus quand même avec epid=None."""
    spider = make_spider()
    item_no_epid = {k: v for k, v in SAMPLE_ITEM.items() if k != "epid"}
    result = spider._parse_item(item_no_epid)
    assert result["epid"] is None
    assert result["title"] is not None  # item toujours là
