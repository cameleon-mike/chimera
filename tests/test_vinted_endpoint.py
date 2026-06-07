"""Tests pour GET /vinted/search."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

_TEST_TOKEN = "test-token"  # noqa: S105
HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}

MOCK_SCRAPY_SUCCESS = {
    "tool": "scrapy",
    "url": "https://www.vinted.fr/catalog?search_text=wacom",
    "http_status": 200,
    "proxy": None,
    "risk_score": 0.1,
    "items": [
        {
            "title": "Wacom Intuos Pro M",
            "price_eur": 85.0,
            "price_raw": "85,00 €",
            "url": "https://www.vinted.fr/items/123456789-wacom-intuos",
            "photo_url": "https://images.vinted.net/123.jpg",
            "source": "vinted",
            "listing_id": "123456789",
            "brand": "Wacom",
            "condition": "very_good",
        },
    ],
    "_meta": {
        "spider": "vinted",
        "item_count": 1,
        "recaptcha_detected": False,
        "blocked": False,
    },
    "_escalation": {"needed": False},
}

MOCK_SCRAPY_BLOCKED = {
    "tool": "scrapy",
    "url": "https://www.vinted.fr/catalog?search_text=wacom",
    "http_status": 403,
    "proxy": None,
    "risk_score": 0.9,
    "items": [],
    "_meta": {
        "spider": "vinted",
        "item_count": 0,
        "recaptcha_detected": False,
        "blocked": True,
    },
    "_escalation": {"needed": True},
}


@pytest.fixture
def client():
    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides[require_bearer] = lambda: _TEST_TOKEN
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)


def test_vinted_no_token():
    """Sans auth → 401."""
    backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        c = TestClient(app)
        resp = c.get("/vinted/search", params={"q": "wacom"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(backup)
    assert resp.status_code == 401


def test_vinted_no_query(client):
    """Sans q → 422."""
    resp = client.get("/vinted/search", headers=HEADERS)
    assert resp.status_code == 422


def test_vinted_success(client):
    """Mock spider → 200 + items."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_SUCCESS):
        resp = client.get("/vinted/search", headers=HEADERS, params={"q": "wacom intuos", "tool": "scrapy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 1
    assert len(data["items"]) == 1


def test_vinted_schema_aggregated_item(client):
    """Schema AggregatedItem valide."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_SUCCESS):
        resp = client.get("/vinted/search", headers=HEADERS, params={"q": "wacom", "tool": "scrapy"})
    data = resp.json()
    item = data["items"][0]
    assert "title" in item
    assert "price" in item
    assert "link" in item
    assert "source" in item


def test_vinted_source_all_items(client):
    """source='vinted' sur tous les items retournés."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_SUCCESS):
        resp = client.get("/vinted/search", headers=HEADERS, params={"q": "wacom", "tool": "scrapy"})
    data = resp.json()
    for item in data["items"]:
        assert item["source"] == "vinted"


def test_vinted_blocked_graceful(client):
    """Blocked gracieux — pas de 500, total_items=0, blocked=True."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_BLOCKED):
        resp = client.get("/vinted/search", headers=HEADERS, params={"q": "wacom", "tool": "scrapy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 0
    assert data["blocked"] is True


MOCK_CRAWL4AI_SUCCESS = {
    "tool": "crawl4ai",
    "url": "https://www.vinted.fr/catalog?search_text=wacom",
    "markdown": "# Wacom listings\n- Wacom Intuos Pro M 85,00 EUR",
    "markdown_len": 42,
}

MOCK_LLM_ITEMS = [
    {
        "listing_id": "123456789",
        "title": "Wacom Intuos Pro M",
        "price_eur": 85.0,
        "price_raw": "85,00 EUR",
        "brand": "Wacom",
        "size": None,
        "condition": "very_good",
        "url": "https://www.vinted.fr/items/123456789-wacom-intuos",
        "photo_url": "https://images.vinted.net/123.jpg",
    },
]


def test_vinted_crawl4ai_default(client):
    """Default tool=crawl4ai -> markdown -> LLM extraction -> items."""
    with patch("bridge.workers._run_crawl4ai_subprocess", return_value=MOCK_CRAWL4AI_SUCCESS), \
         patch(
             "tools.extractors.universal_extractor.UniversalExtractor._llm_extract",
             return_value=MOCK_LLM_ITEMS,
         ):
        resp = client.get("/vinted/search", headers=HEADERS, params={"q": "wacom intuos"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_used"] == "crawl4ai"
    assert data["total_items"] == 1
    assert data["items"][0]["source"] == "vinted"
    assert data["items"][0]["price"]["value"] == 85.0


def test_vinted_crawl4ai_captcha_blocked(client):
    """Captcha in crawl4ai markdown -> graceful blocked, no 500."""
    blocked = {"tool": "crawl4ai", "markdown": "Please complete the captcha to continue", "markdown_len": 40}
    with patch("bridge.workers._run_crawl4ai_subprocess", return_value=blocked):
        resp = client.get("/vinted/search", headers=HEADERS, params={"q": "wacom"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 0
    assert data["blocked"] is True
