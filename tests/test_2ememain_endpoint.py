"""Tests pour GET /2ememain/search."""
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
    "url": "https://www.2ememain.be/q/wacom/",
    "http_status": 200,
    "proxy": None,
    "risk_score": 0.1,
    "items": [
        {
            "title": "Wacom Cintiq 16",
            "price": {"value": 350.0, "currency": "EUR"},
            "start_date": "2026-05-27",
            "end_date": None,
            "photo_url": "https://images.2dehands.be/api/image/123.jpg",
            "link": "https://www.2ememain.be/a/item/123.html",
            "location": "Bruxelles",
            "source": "2ememain",
        },
        {
            "title": "Wacom Intuos Pro M",
            "price": {"value": 120.0, "currency": "EUR"},
            "start_date": "2026-05-26",
            "end_date": None,
            "photo_url": None,
            "link": "https://www.2ememain.be/a/item/456.html",
            "location": "Gent",
            "source": "2ememain",
        },
    ],
    "_meta": {
        "spider": "2ememain",
        "item_count": 2,
        "recaptcha_detected": False,
        "blocked": False,
    },
    "_escalation": {"needed": False},
}

MOCK_SCRAPY_BLOCKED = {
    "tool": "scrapy",
    "url": "https://www.2ememain.be/q/wacom/",
    "http_status": 403,
    "proxy": None,
    "risk_score": 0.9,
    "items": [],
    "_meta": {
        "spider": "2ememain",
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


def test_2ememain_no_token():
    """Sans auth → 401."""
    backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        c = TestClient(app)
        resp = c.get("/2ememain/search", params={"q": "wacom"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(backup)
    assert resp.status_code == 401


def test_2ememain_no_query(client):
    """Sans q → 422."""
    resp = client.get("/2ememain/search", headers=HEADERS)
    assert resp.status_code == 422


def test_2ememain_success(client):
    """Scrapy retourne des items → 200, champs corrects."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_SUCCESS):
        resp = client.get(
            "/2ememain/search",
            headers=HEADERS,
            params={"q": "wacom cintiq"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "wacom cintiq"
    assert data["total_items"] == 2
    assert data["tool_used"] == "scrapy"
    assert data["blocked"] is False


def test_2ememain_success_item_fields(client):
    """Items retournés ont les bons champs."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_SUCCESS):
        resp = client.get(
            "/2ememain/search",
            headers=HEADERS,
            params={"q": "wacom"},
        )
    data = resp.json()
    item = data["items"][0]
    assert item["title"] == "Wacom Cintiq 16"
    assert item["price"]["value"] == 350.0
    assert item["price"]["currency"] == "EUR"
    assert item["start_date"] == "2026-05-27"
    assert item["end_date"] is None
    assert item["location"] == "Bruxelles"
    assert item["source"] == "2ememain"
    assert "2ememain.be" in item["link"]


def test_2ememain_blocked(client):
    """Site bloqué → escalade screenshot+groq. Si groq échoue → 200 escalation_error."""
    with (
        patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_BLOCKED),
        patch("bridge.workers._run_screenshot_subprocess", side_effect=RuntimeError("API error")),
    ):
        resp = client.get(
            "/2ememain/search",
            headers=HEADERS,
            params={"q": "wacom"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 0
    assert data["items"] == []
    assert data["blocked"] is True
    assert data["tool_used"] == "escalation_error"


def test_2ememain_response_fields_present(client):
    """Tous les champs obligatoires présents."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_SUCCESS):
        resp = client.get(
            "/2ememain/search",
            headers=HEADERS,
            params={"q": "test"},
        )
    data = resp.json()
    for field in ("query", "total_items", "items", "tool_used", "blocked", "ts"):
        assert field in data, f"Champ manquant: {field}"


def test_2ememain_max_pages_forwarded(client):
    """max_pages est transmis au subprocess."""
    captured = {}

    def mock_scrapy(job_id, url, config):
        captured["config"] = config
        return MOCK_SCRAPY_SUCCESS

    with patch("bridge.workers._run_scrapy_subprocess", side_effect=mock_scrapy):
        resp = client.get(
            "/2ememain/search",
            headers=HEADERS,
            params={"q": "wacom", "max_pages": 2},
        )
    assert resp.status_code == 200
    assert captured["config"]["max_pages"] == 2


def test_2ememain_default_max_pages(client):
    """max_pages default = 3."""
    captured = {}

    def mock_scrapy(job_id, url, config):
        captured["config"] = config
        return MOCK_SCRAPY_SUCCESS

    with patch("bridge.workers._run_scrapy_subprocess", side_effect=mock_scrapy):
        client.get("/2ememain/search", headers=HEADERS, params={"q": "wacom"})
    assert captured["config"]["max_pages"] == 3


def test_2ememain_spider_param_forwarded(client):
    """config.spider='2ememain' transmis au subprocess."""
    captured = {}

    def mock_scrapy(job_id, url, config):
        captured["config"] = config
        return MOCK_SCRAPY_SUCCESS

    with patch("bridge.workers._run_scrapy_subprocess", side_effect=mock_scrapy):
        client.get("/2ememain/search", headers=HEADERS, params={"q": "wacom"})
    assert captured["config"]["spider"] == "2ememain"


def test_2ememain_schema_models():
    """TwoememainItem et TwoememainSearchResponse valides depuis bridge.schemas."""
    from datetime import datetime, timezone
    from bridge.schemas import EbayPrice, TwoememainItem, TwoememainSearchResponse

    price = EbayPrice(value=350.0, currency="EUR")
    item = TwoememainItem(
        title="Wacom Cintiq 16",
        price=price,
        start_date="2026-05-27",
        location="Bruxelles",
        link="https://www.2ememain.be/a/item/123.html",
    )
    assert item.source == "2ememain"
    assert item.end_date is None

    resp = TwoememainSearchResponse(
        query="wacom",
        total_items=1,
        items=[item],
        tool_used="scrapy",
        ts=datetime.now(timezone.utc).isoformat(),
    )
    assert resp.total_items == 1
    assert resp.blocked is False


def test_2ememain_empty_items_success(client):
    """0 items sans blocked → 200 normal, pas une erreur."""
    empty_result = dict(MOCK_SCRAPY_SUCCESS, items=[], _meta={**MOCK_SCRAPY_SUCCESS["_meta"], "item_count": 0})
    with patch("bridge.workers._run_scrapy_subprocess", return_value=empty_result):
        resp = client.get(
            "/2ememain/search",
            headers=HEADERS,
            params={"q": "objet-inexistant-xyz"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 0
    assert data["blocked"] is False
