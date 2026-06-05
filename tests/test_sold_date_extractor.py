"""Tests pour tools.vision_agent.extract_sold_dates.SoldDateExtractor."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tools.vision_agent.extract_sold_dates import SoldDateExtractor, _PROMPT

_PNG_BYTES = b"\x89PNG\r\n\x1a\n"


def _make_mock_client(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def test_extract_from_screenshot_returns_list(tmp_path):
    """Mock Groq returns valid JSON → returns list[dict]."""
    png_file = tmp_path / "shot.png"
    png_file.write_bytes(_PNG_BYTES)

    mock_client = _make_mock_client(
        '[{"title": "Wacom", "end_date": "2026-05-15", "price": 280.0, "watch_count": 42}]'
    )
    with patch("groq.Groq", return_value=mock_client):
        extractor = SoldDateExtractor(groq_api_key="test_key")
        result = extractor.extract_from_screenshot(str(png_file))

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["title"] == "Wacom"
    assert result[0]["end_date"] == "2026-05-15"


def test_extract_from_screenshot_groq_down_returns_empty(tmp_path):
    """Groq raises RuntimeError → returns []."""
    png_file = tmp_path / "shot.png"
    png_file.write_bytes(_PNG_BYTES)

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("Groq unavailable")
    with patch("groq.Groq", return_value=mock_client):
        extractor = SoldDateExtractor(groq_api_key="test_key")
        result = extractor.extract_from_screenshot(str(png_file))

    assert result == []


def test_extract_from_screenshot_invalid_json_returns_empty(tmp_path):
    """Groq returns invalid JSON → returns []."""
    png_file = tmp_path / "shot.png"
    png_file.write_bytes(_PNG_BYTES)

    mock_client = _make_mock_client("not json at all")
    with patch("groq.Groq", return_value=mock_client):
        extractor = SoldDateExtractor(groq_api_key="test_key")
        result = extractor.extract_from_screenshot(str(png_file))

    assert result == []


def test_parse_date_english_full():
    """'May 15, 2026' → '2026-05-15'."""
    with patch("groq.Groq", return_value=MagicMock()):
        extractor = SoldDateExtractor(groq_api_key="test_key")
    assert extractor._parse_date("May 15, 2026") == "2026-05-15"


def test_parse_date_french():
    """'15 mai 2026' → '2026-05-15'."""
    with patch("groq.Groq", return_value=MagicMock()):
        extractor = SoldDateExtractor(groq_api_key="test_key")
    assert extractor._parse_date("15 mai 2026") == "2026-05-15"


def test_parse_date_sold_prefix():
    """'Sold May 15' → '<current_year>-05-15'."""
    current_year = datetime.now().year
    with patch("groq.Groq", return_value=MagicMock()):
        extractor = SoldDateExtractor(groq_api_key="test_key")
    assert extractor._parse_date("Sold May 15") == f"{current_year}-05-15"


def test_parse_date_unparseable_returns_none():
    """'gibberish' → None."""
    with patch("groq.Groq", return_value=MagicMock()):
        extractor = SoldDateExtractor(groq_api_key="test_key")
    assert extractor._parse_date("gibberish") is None


def test_extract_from_png_bytes_no_disk():
    """Pass bytes directly → returns list (mock Groq)."""
    mock_client = _make_mock_client(
        '[{"title": "Wacom", "end_date": "2026-05-15", "price": 280.0, "watch_count": 42}]'
    )
    with patch("groq.Groq", return_value=mock_client):
        extractor = SoldDateExtractor(groq_api_key="test_key")
        result = extractor.extract_from_png_bytes(_PNG_BYTES)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["end_date"] == "2026-05-15"


def test_prompt_contains_sold_items():
    """Verify _PROMPT contains 'sold' and 'end_date'."""
    assert "sold" in _PROMPT.lower()
    assert "end_date" in _PROMPT


def test_items_without_end_date_filtered():
    """Groq returns items without end_date → they are filtered out."""
    mock_client = _make_mock_client(
        '[{"title": "Wacom", "price": 280.0, "watch_count": 42}]'
    )
    with patch("groq.Groq", return_value=mock_client):
        extractor = SoldDateExtractor(groq_api_key="test_key")
        result = extractor.extract_from_png_bytes(_PNG_BYTES)

    assert result == []
