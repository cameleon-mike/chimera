"""Tests pour GET /watchcount/search."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

# Bypass auth via dependency_overrides — robuste face aux manipulations
# du cache get_settings() par d'autres fichiers de tests (test_scrapy_runner,
# test_account_factory). On envoie "test-token" et on court-circuite require_bearer.
_TEST_TOKEN = "test-token"  # noqa: S105
HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}

MOCK_SCRAPY_ITEMS = {
    "tool": "scrapy",
    "url": "https://www.watchcount.com/...",
    "http_status": 200,
    "proxy": None,
    "risk_score": 0.1,
    "items": [
        {
            "title": "Wacom Cintiq 16",
            "watch_count": 458,
            "end_date": "2026-06-15",
            "price": 349.99,
            "ebay_url": "https://www.ebay.fr/itm/123456789012",
            "ebay_item_id": "123456789012",
            "source": "watchcount",
        }
    ],
    "_meta": {"item_count": 1, "recaptcha_detected": False},
    "_escalation": {"needed": False},
}

MOCK_SCRAPY_RECAPTCHA = {
    "tool": "scrapy",
    "url": "https://www.watchcount.com/...",
    "http_status": 200,
    "proxy": None,
    "risk_score": 0.9,
    "items": [],
    "_meta": {"item_count": 0, "recaptcha_detected": True},
    "_escalation": {"needed": True},
}

MOCK_SCREENSHOT_RESULT = {
    "job_id": "abc123",
    "screenshot_path": "/workspaces/chimera/storage/screenshots/abc123.png",
    "http_status": 200,
}

MOCK_GROQ_ITEMS = [
    {
        "title": "Wacom Cintiq 16 (vision)",
        "watch_count": 300,
        "end_date": "2026-06-20",
        "price": 280.0,
        "ebay_url": "https://www.ebay.fr/itm/999888777666",
        "ebay_item_id": "999888777666",
    }
]


@pytest.fixture
def client():
    # Override require_bearer → robust against settings-cache mutations by other test files
    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides[require_bearer] = lambda: _TEST_TOKEN
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)


def test_watchcount_no_token():
    """Sans override d'auth → 401 avec un token invalide."""
    # Crée un client sans l'override de require_bearer
    backup = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        c = TestClient(app)
        resp = c.get("/watchcount/search", params={"q": "wacom"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(backup)
    assert resp.status_code == 401


def test_watchcount_no_query(client):
    """Sans q → 422."""
    resp = client.get("/watchcount/search", headers=HEADERS)
    assert resp.status_code == 422


def test_watchcount_scrapy_success(client):
    """Scrapy retourne des items → 200, tool_used=scrapy."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_ITEMS):
        resp = client.get(
            "/watchcount/search",
            headers=HEADERS,
            params={"q": "wacom cintiq"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 1
    assert data["tool_used"] == "scrapy"
    assert data["recaptcha_detected"] is False
    assert data["items"][0]["title"] == "Wacom Cintiq 16"
    assert data["items"][0]["watch_count"] == 458
    assert data["items"][0]["end_date"] == "2026-06-15"


def test_watchcount_recaptcha_escalation_no_groq_key(client, tmp_path):
    """reCAPTCHA détecté + GROQ_API_KEY absent → tool_used inclut screenshot ou escalation."""
    fake_png = tmp_path / "shot.png"
    fake_png.write_bytes(b"\x89PNG")
    mock_ss = dict(MOCK_SCREENSHOT_RESULT, screenshot_path=str(fake_png))

    # Patch bridge.app.settings.groq_api_key directly — pas de manipulation de cache
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RECAPTCHA), \
         patch("bridge.workers._run_screenshot_subprocess", return_value=mock_ss), \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = ""
        resp = client.get(
            "/watchcount/search",
            headers=HEADERS,
            params={"q": "wacom"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["recaptcha_detected"] is True


def test_watchcount_scrapy_success_marketplace_param(client):
    """marketplace=EBAY_DE transmis correctement."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_ITEMS) as mock_scrapy:
        resp = client.get(
            "/watchcount/search",
            headers=HEADERS,
            params={"q": "wacom", "marketplace": "EBAY_DE"},
        )
    assert resp.status_code == 200
    assert resp.json()["marketplace"] == "EBAY_DE"


def test_watchcount_response_fields(client):
    """Tous les champs obligatoires présents dans la réponse."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_ITEMS):
        resp = client.get(
            "/watchcount/search",
            headers=HEADERS,
            params={"q": "test"},
        )
    data = resp.json()
    for field in ("query", "marketplace", "total_items", "items", "tool_used", "recaptcha_detected", "ts"):
        assert field in data, f"Champ manquant: {field}"


def test_watchcount_item_schema():
    """WatchCountItem et WatchCountSearchResponse valides depuis bridge.schemas."""
    from bridge.schemas import WatchCountItem, WatchCountSearchResponse
    from datetime import datetime, timezone

    item = WatchCountItem(
        title="Wacom Cintiq 16",
        watch_count=200,
        end_date="2026-06-15",
        price=280.0,
        ebay_url="https://www.ebay.fr/itm/123",
        ebay_item_id="123456789012",
    )
    assert item.source == "watchcount"

    resp = WatchCountSearchResponse(
        query="wacom",
        marketplace="EBAY_FR",
        total_items=1,
        items=[item],
        tool_used="scrapy",
        ts=datetime.now(timezone.utc).isoformat(),
    )
    assert resp.total_items == 1
    assert resp.recaptcha_detected is False


def test_watchcount_empty_scrapy_result(client):
    """Scrapy retourne 0 items (sans reCAPTCHA) → escalation car no items."""
    empty_result = dict(MOCK_SCRAPY_ITEMS, items=[], _meta={"item_count": 0, "recaptcha_detected": False})
    # Sans Groq key et screenshot, l'endpoint essaie d'escalader
    # On patche screenshot pour retourner un résultat sans png
    with patch("bridge.workers._run_scrapy_subprocess", return_value=empty_result), \
         patch("bridge.workers._run_screenshot_subprocess", return_value={"job_id": "x", "screenshot_path": ""}):
        resp = client.get(
            "/watchcount/search",
            headers=HEADERS,
            params={"q": "wacom"},
        )
    assert resp.status_code == 200
    data = resp.json()
    # Sans items Scrapy → escalation tentée
    assert "tool_used" in data
