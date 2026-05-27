"""Tests pour GET /ebay/search."""
import pytest
from unittest.mock import patch, PropertyMock
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.config import get_settings

TOKEN = get_settings().bridge_auth_token
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

MOCK_SCRAPY_RESULT = {
    "tool": "scrapy",
    "url": "https://api.ebay.com/...",
    "http_status": 200,
    "proxy": None,
    "risk_score": 0.1,
    "items": [
        {
            "title": "Wacom Cintiq 16",
            "price": {"value": 250.0, "currency": "EUR"},
            "epid": "12345678",
            "start_date": "2026-05-01",
            "end_date": None,
            "photo_url": "https://img.ebay.com/img.jpg",
            "link": "https://www.ebay.fr/itm/123",
        }
    ],
    "_meta": {"item_count": 1},
    "_escalation": {"needed": False},
}


@pytest.fixture
def client():
    # Clear dependency_overrides set at module-level by other test files
    # (e.g. test_escalate_endpoint.py overrides require_bearer globally)
    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)


def test_ebay_search_no_token(client):
    """Sans token → 401."""
    resp = client.get("/ebay/search", params={"q": "wacom"})
    assert resp.status_code == 401


def test_ebay_search_no_query(client):
    """Sans q → 422."""
    resp = client.get("/ebay/search", headers=HEADERS)
    assert resp.status_code == 422


def test_ebay_search_with_mock(client):
    """Avec mock spider → 200 + items[]."""
    # scraper.env already has EBAY_APP_ID_1 so settings.ebay_app_ids is populated;
    # we only need to stub the subprocess call to avoid a real eBay API hit.
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RESULT):
        resp = client.get("/ebay/search", headers=HEADERS, params={"q": "wacom cintiq"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] >= 0
    assert "items" in data


def test_ebay_search_response_schema(client):
    """Schema EbaySearchResponse valide (champs obligatoires présents)."""
    from bridge.schemas import EbaySearchResponse, EbayItem
    response = EbaySearchResponse(
        query="wacom",
        marketplace="EBAY_FR",
        total_items=1,
        items=[EbayItem(title="Test", price=None, epid="123")],
        api_calls_used=1,
        risk_scores=[0.1],
        ts="2026-05-25T12:00:00+00:00",
    )
    assert response.total_items == 1
    assert response.items[0].title == "Test"


def test_ebay_search_default_marketplace(client):
    """marketplace par défaut EBAY_FR respecté."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RESULT):
        resp = client.get("/ebay/search", headers=HEADERS, params={"q": "wacom"})
    assert resp.status_code == 200
    assert resp.json().get("marketplace") == "EBAY_FR"
