"""Integration tests for /watchcount/search with vision pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bridge.app import app
from bridge.auth import require_bearer

_TEST_TOKEN = "test-token"  # noqa: S105
HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}

MOCK_SCRAPY_ZERO = {
    "items": [],
    "_meta": {"item_count": 0, "recaptcha_detected": False},
    "_escalation": {"needed": False},
}
MOCK_SCRAPY_RECAPTCHA = {
    "items": [],
    "_meta": {"item_count": 0, "recaptcha_detected": True},
    "_escalation": {"needed": True},
}
MOCK_SCREENSHOT_OK = {
    "job_id": "abc123",
    "screenshot_path": "/tmp/fake_shot.png",
    "http_status": 200,
}
MOCK_VISION_ITEMS = [
    {"title": "Wacom Cintiq 16", "end_date": "2026-05-15", "price": 280.0, "watch_count": 42}
]


@pytest.fixture
def client():
    overrides_backup = dict(app.dependency_overrides)
    app.dependency_overrides[require_bearer] = lambda: _TEST_TOKEN
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_backup)


@pytest.fixture
def png_file(tmp_path):
    """Create a minimal PNG file for testing."""
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_zero_scrapy_items_triggers_screenshot(client):
    """scrapy returns 0 items → screenshot runner called."""
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract_from_screenshot.return_value = []

    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_ZERO), \
         patch("bridge.workers._run_screenshot_subprocess") as mock_ss, \
         patch("tools.vision_agent.extract_sold_dates.SoldDateExtractor", return_value=mock_extractor_instance), \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = "fake-key"
        mock_ss.return_value = {"job_id": "x", "screenshot_path": "", "http_status": 200}
        client.get("/watchcount/search", headers=HEADERS, params={"q": "wacom"})

    mock_ss.assert_called_once()


def test_screenshot_ok_vision_called(client, png_file):
    """Screenshot succeeds → SoldDateExtractor called."""
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract_from_screenshot.return_value = []

    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RECAPTCHA), \
         patch("bridge.workers._run_screenshot_subprocess", return_value={
             "job_id": "x",
             "screenshot_path": str(png_file),
             "http_status": 200,
         }), \
         patch("tools.vision_agent.extract_sold_dates.SoldDateExtractor", return_value=mock_extractor_instance) as MockExtractor, \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = "fake-key"
        client.get("/watchcount/search", headers=HEADERS, params={"q": "wacom"})

    MockExtractor.assert_called_once()
    mock_extractor_instance.extract_from_screenshot.assert_called_once_with(str(png_file))


def test_vision_items_returned_in_response(client, png_file):
    """Vision returns items → items in response."""
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract_from_screenshot.return_value = MOCK_VISION_ITEMS

    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RECAPTCHA), \
         patch("bridge.workers._run_screenshot_subprocess", return_value={
             "job_id": "x",
             "screenshot_path": str(png_file),
             "http_status": 200,
         }), \
         patch("tools.vision_agent.extract_sold_dates.SoldDateExtractor", return_value=mock_extractor_instance), \
         patch("bridge.app._ingest_sold_dates"), \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = "fake-key"
        resp = client.get("/watchcount/search", headers=HEADERS, params={"q": "wacom"})

    assert resp.status_code == 200
    assert resp.json()["total_items"] == 1
    assert resp.json()["items"][0]["end_date"] == "2026-05-15"


def test_tool_used_screenshot_vision(client, png_file):
    """tool_used = 'screenshot+vision'."""
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract_from_screenshot.return_value = MOCK_VISION_ITEMS

    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RECAPTCHA), \
         patch("bridge.workers._run_screenshot_subprocess", return_value={
             "job_id": "x",
             "screenshot_path": str(png_file),
             "http_status": 200,
         }), \
         patch("tools.vision_agent.extract_sold_dates.SoldDateExtractor", return_value=mock_extractor_instance), \
         patch("bridge.app._ingest_sold_dates"), \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = "fake-key"
        resp = client.get("/watchcount/search", headers=HEADERS, params={"q": "wacom"})

    assert resp.status_code == 200
    assert resp.json()["tool_used"] == "screenshot+vision"


def test_vision_down_graceful(client, png_file):
    """SoldDateExtractor raises → no 500, total_items == 0."""
    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RECAPTCHA), \
         patch("bridge.workers._run_screenshot_subprocess", return_value={
             "job_id": "x",
             "screenshot_path": str(png_file),
             "http_status": 200,
         }), \
         patch("tools.vision_agent.extract_sold_dates.SoldDateExtractor", side_effect=RuntimeError("Groq down")), \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = "fake-key"
        resp = client.get("/watchcount/search", headers=HEADERS, params={"q": "wacom"})

    assert resp.status_code == 200
    assert resp.json()["total_items"] == 0


def test_ingest_end_dates_calls_recompute(client, png_file):
    """Vision items with end_dates → _ingest_sold_dates called."""
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract_from_screenshot.return_value = MOCK_VISION_ITEMS

    with patch("bridge.workers._run_scrapy_subprocess", return_value=MOCK_SCRAPY_RECAPTCHA), \
         patch("bridge.workers._run_screenshot_subprocess", return_value={
             "job_id": "x",
             "screenshot_path": str(png_file),
             "http_status": 200,
         }), \
         patch("tools.vision_agent.extract_sold_dates.SoldDateExtractor", return_value=mock_extractor_instance), \
         patch("bridge.app._ingest_sold_dates") as mock_ingest, \
         patch("bridge.app.settings") as mock_settings:
        mock_settings.groq_api_key = "fake-key"
        resp = client.get("/watchcount/search", headers=HEADERS, params={"q": "wacom"})

    assert resp.status_code == 200
    mock_ingest.assert_called_once_with(MOCK_VISION_ITEMS)
