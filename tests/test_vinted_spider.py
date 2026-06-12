"""Tests pour VintedSpider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import scrapy
from scrapy.http import Request, TextResponse

from tools.scrapy_runner.project.spiders.vinted_spider import VintedSpider


def make_spider(**kwargs) -> VintedSpider:
    return VintedSpider(q="wacom intuos pro", groq_api_key="", **kwargs)


def make_response(body: str, url: str = "https://www.vinted.fr/catalog?search_text=wacom", status: int = 200) -> TextResponse:
    req = Request(url=url)
    return TextResponse(url=url, body=body.encode("utf-8"), encoding="utf-8", request=req, status=status)


SAMPLE_HTML = """
<html><body>
<div data-testid="grid-item">
  <a href="/items/123456789-wacom-intuos" title="Wacom Intuos Pro M">
    <img src="https://images.vinted.net/123.jpg" />
  </a>
  <div data-testid="product-item-id-123456789--price-text">85,00 €</div>
  <div data-testid="product-item-id-123456789--description-title">Wacom</div>
  <div data-testid="product-item-id-123456789--description-subtitle">Très bon état</div>
</div>
</body></html>
"""


def parse_items_only(spider, resp) -> list[dict]:
    return [x for x in spider.parse(resp) if isinstance(x, dict)]


def test_spider_parse_items():
    """Spider parse items depuis HTML fixture."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    assert len(items) >= 1


def test_spider_price_extracted():
    """Prix extrait correctement."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    assert items[0]["price_eur"] == pytest.approx(85.0)


def test_spider_url_correct():
    """URL item correcte."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    assert "/items/123456789" in items[0]["url"]


def test_spider_photo_url():
    """photo_url extraite."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    assert "images.vinted.net" in items[0]["photo_url"]


def test_spider_invalid_items_ignored():
    """Items invalides (prix=0) ignorés."""
    html = """
    <html><body>
    <div data-testid="item-card">
      <a href="/items/999">
        <span data-testid="item-title">Item sans prix</span>
        <div data-testid="item-price"><span>gratuit</span></div>
        <img src="https://images.vinted.net/999.jpg" />
      </a>
    </div>
    </body></html>
    """
    spider = make_spider()
    items = parse_items_only(spider, make_response(html))
    assert items == []


def test_spider_source_vinted():
    """Tous les items ont source='vinted'."""
    spider = make_spider()
    items = parse_items_only(spider, make_response(SAMPLE_HTML))
    for item in items:
        assert item["source"] == "vinted"


def test_spider_blocked_403():
    """HTTP 403 → _blocked=True, aucun item."""
    spider = make_spider()
    resp = make_response("<html><body>Forbidden</body></html>", status=403)
    items = list(spider.parse(resp))
    assert items == []
    assert spider._blocked is True


def test_spider_name():
    """Spider name est 'vinted'."""
    assert VintedSpider.name == "vinted"
