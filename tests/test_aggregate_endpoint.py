"""Tests pour GET /aggregate/search."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer
from bridge.aggregator import deduplicate, _normalize, _similar_titles, _prices_close
from bridge.schemas import AggregatedItem, EbayItem, EbayPrice, TwoememainItem

_TEST_TOKEN = "test-token"  # noqa: S105
HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}

# ---------------------------------------------------------------------------
# Fixtures / mocks
# ---------------------------------------------------------------------------

MOCK_EBAY_RAW = {
    "items": [
        {
            "title": "Wacom Cintiq 16 tablette graphique",
            "price": {"value": 250.0, "currency": "EUR"},
            "epid": "12345678",
            "start_date": "2026-05-01",
            "end_date": None,
            "photo_url": "https://img.ebay.com/img.jpg",
            "link": "https://www.ebay.fr/itm/123",
        },
        {
            "title": "Wacom Intuos Pro M",
            "price": {"value": 120.0, "currency": "EUR"},
            "epid": None,
            "start_date": "2026-04-20",
            "end_date": None,
            "photo_url": None,
            "link": "https://www.ebay.fr/itm/456",
        },
    ],
    "_meta": {"item_count": 2},
}

MOCK_2EMEMAIN_RAW = {
    "items": [
        {
            # near-duplicate of eBay item 0 (same title, close price)
            "title": "Wacom Cintiq 16 tablette graphique",
            "price": {"value": 260.0, "currency": "EUR"},
            "start_date": "2026-05-10",
            "end_date": None,
            "photo_url": "https://img.2dehands.be/img.jpg",
            "link": "https://www.2ememain.be/a/item/99.html",
            "location": "Bruxelles",
        },
        {
            # unique item — not on eBay
            "title": "Wacom Bamboo Fun Medium",
            "price": {"value": 40.0, "currency": "EUR"},
            "start_date": "2026-05-15",
            "end_date": None,
            "photo_url": None,
            "link": "https://www.2ememain.be/a/item/77.html",
            "location": "Liège",
        },
    ],
    "_meta": {"blocked": False, "item_count": 2},
}

MOCK_2EMEMAIN_BLOCKED = {
    "items": [],
    "_meta": {"blocked": True, "item_count": 0},
}


@pytest.fixture()
def raw_client():
    """TestClient sans override auth — pour tester les 401."""
    backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(backup)


@pytest.fixture()
def client():
    backup = dict(app.dependency_overrides)
    app.dependency_overrides[require_bearer] = lambda: _TEST_TOKEN
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(backup)


# ---------------------------------------------------------------------------
# Unit tests — aggregator logic
# ---------------------------------------------------------------------------


def test_normalize_empty():
    assert _normalize(None) == ""
    assert _normalize("") == ""


def test_normalize_strips_punctuation():
    assert _normalize("Wacom Cintiq 16!") == "wacom cintiq 16"


def test_similar_titles_identical():
    assert _similar_titles("Wacom Cintiq 16", "Wacom Cintiq 16") is True


def test_similar_titles_threshold():
    assert _similar_titles("Wacom Cintiq 16 tablette", "Wacom Cintiq 16 tablette graphique") is True
    assert _similar_titles("Wacom", "Canon EOS R5") is False


def test_similar_titles_none():
    assert _similar_titles(None, "anything") is False
    assert _similar_titles("anything", None) is False


def test_prices_close_within_tolerance():
    assert _prices_close(100.0, 120.0) is True    # 20/120 = 17% ≤ 25%
    assert _prices_close(100.0, 130.0) is True    # 30/130 = 23% ≤ 25%
    assert _prices_close(100.0, 150.0) is False   # 50/150 = 33% > 25%


def test_prices_close_none_values():
    assert _prices_close(None, 100.0) is True
    assert _prices_close(100.0, None) is True
    assert _prices_close(None, None) is True


def test_prices_close_zero():
    assert _prices_close(0.0, 0.0) is True


def _make_ebay(title, price_val):
    price = EbayPrice(value=price_val, currency="EUR") if price_val is not None else None
    return EbayItem(title=title, price=price, link=f"https://ebay.fr/{title[:5]}")


def _make_deux(title, price_val, location="Paris"):
    price = EbayPrice(value=price_val, currency="EUR") if price_val is not None else None
    return TwoememainItem(title=title, price=price, location=location,
                          link=f"https://2ememain.be/{title[:5]}")


def test_deduplicate_removes_near_dup():
    ebay = [_make_ebay("Wacom Cintiq 16 tablette graphique", 250.0)]
    deux = [
        _make_deux("Wacom Cintiq 16 tablette graphique", 260.0),  # dup
        _make_deux("Wacom Bamboo Fun Medium", 40.0),               # unique
    ]
    merged, n_dups = deduplicate(ebay, deux)
    assert n_dups == 1
    assert len(merged) == 2
    sources = [i.source for i in merged]
    assert "ebay" in sources
    assert "2ememain" in sources


def test_deduplicate_keeps_unique():
    ebay = [_make_ebay("Canon EOS R5", 2500.0)]
    deux = [_make_deux("Nikon D850", 1800.0)]
    merged, n_dups = deduplicate(ebay, deux)
    assert n_dups == 0
    assert len(merged) == 2


def test_deduplicate_empty_sources():
    merged, n_dups = deduplicate([], [])
    assert merged == []
    assert n_dups == 0


def test_deduplicate_only_ebay():
    ebay = [_make_ebay("Canon EOS R5", 2500.0)]
    merged, n_dups = deduplicate(ebay, [])
    assert len(merged) == 1
    assert merged[0].source == "ebay"
    assert n_dups == 0


def test_deduplicate_only_2ememain():
    deux = [_make_deux("Wacom Bamboo", 40.0)]
    merged, n_dups = deduplicate([], deux)
    assert len(merged) == 1
    assert merged[0].source == "2ememain"
    assert n_dups == 0


def test_deduplicate_price_far_off_keeps_item():
    # Same title but very different price → NOT a duplicate
    ebay = [_make_ebay("Wacom Cintiq 16", 250.0)]
    deux = [_make_deux("Wacom Cintiq 16", 800.0)]
    merged, n_dups = deduplicate(ebay, deux)
    assert n_dups == 0
    assert len(merged) == 2


def test_deduplicate_source_field():
    ebay = [_make_ebay("Canon EOS R5", 2500.0)]
    deux = [_make_deux("Nikon D850", 1800.0)]
    merged, _ = deduplicate(ebay, deux)
    sources = {i.source for i in merged}
    assert sources == {"ebay", "2ememain"}


# ---------------------------------------------------------------------------
# Integration tests — endpoint
# ---------------------------------------------------------------------------


def test_aggregate_search_no_auth(raw_client):
    r = raw_client.get("/aggregate/search", params={"q": "wacom"})
    assert r.status_code == 401


@patch("bridge.aggregator.fetch_ebay_raw")
@patch("bridge.aggregator.fetch_2ememain_raw")
def test_aggregate_search_success(mock_deux, mock_ebay, client):
    mock_ebay.return_value = MOCK_EBAY_RAW
    mock_deux.return_value = MOCK_2EMEMAIN_RAW

    r = client.get("/aggregate/search", params={"q": "wacom"}, headers=HEADERS)
    assert r.status_code == 200
    data = r.json()

    assert data["query"] == "wacom"
    assert data["marketplace"] == "EBAY_FR"
    # 2 eBay + 2 2ememain - 1 dup = 3
    assert data["total_items"] == 3
    assert data["duplicates_removed"] == 1
    assert data["sources"]["ebay"] == 2
    assert data["sources"]["2ememain"] == 1
    assert data["twoememain_blocked"] is False

    sources = [i["source"] for i in data["items"]]
    assert "ebay" in sources
    assert "2ememain" in sources


@patch("bridge.aggregator.fetch_ebay_raw")
@patch("bridge.aggregator.fetch_2ememain_raw")
def test_aggregate_search_2ememain_blocked(mock_deux, mock_ebay, client):
    mock_ebay.return_value = MOCK_EBAY_RAW
    mock_deux.return_value = MOCK_2EMEMAIN_BLOCKED

    r = client.get("/aggregate/search", params={"q": "wacom"}, headers=HEADERS)
    assert r.status_code == 200
    data = r.json()

    assert data["twoememain_blocked"] is True
    assert data["sources"]["2ememain"] == 0
    assert data["sources"]["ebay"] == 2
    assert data["duplicates_removed"] == 0


@patch("bridge.aggregator.fetch_ebay_raw")
@patch("bridge.aggregator.fetch_2ememain_raw")
def test_aggregate_search_ebay_empty(mock_deux, mock_ebay, client):
    mock_ebay.return_value = {"items": [], "_meta": {}}
    mock_deux.return_value = MOCK_2EMEMAIN_RAW

    r = client.get("/aggregate/search", params={"q": "wacom"}, headers=HEADERS)
    assert r.status_code == 200
    data = r.json()

    assert data["sources"]["ebay"] == 0
    assert data["sources"]["2ememain"] == 2
    assert data["duplicates_removed"] == 0
    assert data["total_items"] == 2


@patch("bridge.aggregator.fetch_ebay_raw")
@patch("bridge.aggregator.fetch_2ememain_raw")
def test_aggregate_search_marketplace_param(mock_deux, mock_ebay, client):
    mock_ebay.return_value = {"items": [], "_meta": {}}
    mock_deux.return_value = {"items": [], "_meta": {"blocked": False}}

    r = client.get(
        "/aggregate/search",
        params={"q": "nikon", "marketplace": "EBAY_BE", "max_pages": 2},
        headers=HEADERS,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["marketplace"] == "EBAY_BE"
    assert data["total_items"] == 0

    call_args = mock_ebay.call_args
    assert call_args[0][1] == "EBAY_BE"
    assert call_args[0][2] == 2


@patch("bridge.aggregator.fetch_ebay_raw")
@patch("bridge.aggregator.fetch_2ememain_raw")
def test_aggregate_search_response_schema(mock_deux, mock_ebay, client):
    mock_ebay.return_value = MOCK_EBAY_RAW
    mock_deux.return_value = MOCK_2EMEMAIN_RAW

    r = client.get("/aggregate/search", params={"q": "wacom"}, headers=HEADERS)
    data = r.json()

    required_keys = {"query", "marketplace", "total_items", "items", "sources",
                     "duplicates_removed", "ebay_blocked", "twoememain_blocked", "ts"}
    assert required_keys.issubset(set(data.keys()))

    for item in data["items"]:
        assert "source" in item
        assert item["source"] in ("ebay", "2ememain")
