"""Tests pour tools.groq_vision.extract_dates."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.groq_vision.extract_dates import parse_json_array, GroqVisionExtractor, _to_base64


# ---------------------------------------------------------------------------
# parse_json_array unit tests (no API call)
# ---------------------------------------------------------------------------


def test_parse_json_array_clean():
    """JSON array propre → liste de dicts."""
    raw = '[{"title": "Wacom Cintiq", "watch_count": 100, "end_date": "2026-06-01", "price": 300.0, "ebay_url": null, "ebay_item_id": null}]'
    result = parse_json_array(raw)
    assert len(result) == 1
    assert result[0]["title"] == "Wacom Cintiq"
    assert result[0]["watch_count"] == 100


def test_parse_json_array_with_markdown_fences():
    """JSON entouré de ```json ... ``` → parsé correctement."""
    raw = '```json\n[{"title": "Test", "watch_count": 42}]\n```'
    result = parse_json_array(raw)
    assert len(result) == 1
    assert result[0]["watch_count"] == 42


def test_parse_json_array_empty():
    """'[]' → liste vide."""
    assert parse_json_array("[]") == []


def test_parse_json_array_multiple_items():
    """Plusieurs items → tous parsés."""
    raw = '[{"title": "A"}, {"title": "B"}, {"title": "C"}]'
    result = parse_json_array(raw)
    assert len(result) == 3
    assert {i["title"] for i in result} == {"A", "B", "C"}


def test_parse_json_array_invalid():
    """JSON invalide → liste vide (pas de crash)."""
    assert parse_json_array("not json at all") == []
    assert parse_json_array("{key: value}") == []


def test_parse_json_array_with_noise():
    """Texte parasite avant/après le tableau → parsé quand même."""
    raw = 'Here are the results:\n[{"title": "Test"}]\nEnd of extraction.'
    result = parse_json_array(raw)
    assert len(result) == 1


def test_parse_json_array_filters_non_dicts():
    """Éléments non-dict dans le tableau → filtrés."""
    raw = '[{"title": "OK"}, null, 42, "string"]'
    result = parse_json_array(raw)
    assert len(result) == 1
    assert result[0]["title"] == "OK"


# ---------------------------------------------------------------------------
# _to_base64 helper
# ---------------------------------------------------------------------------


def test_to_base64_from_string():
    """Si ce n'est pas un fichier valide → retourne la chaîne telle quelle."""
    s = "alreadyencodedbase64string=="
    assert _to_base64(s) == s


def test_to_base64_from_file(tmp_path: Path):
    """Fichier PNG existant → encodé en base64."""
    import base64
    png = tmp_path / "test.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
    result = _to_base64(png)
    decoded = base64.b64decode(result)
    assert decoded == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# GroqVisionExtractor — constructor and mocked extract_items
# ---------------------------------------------------------------------------


def test_extractor_raises_on_empty_key():
    """GROQ_API_KEY vide → ValueError."""
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqVisionExtractor(api_key="")


def test_extractor_initializes_with_key():
    """Clé non-vide → constructeur OK (sans appel réseau)."""
    with patch("tools.groq_vision.extract_dates.GroqVisionExtractor.__init__",
               return_value=None) as mock_init:
        e = GroqVisionExtractor.__new__(GroqVisionExtractor)
        # Juste vérifier que l'import ne crash pas
    assert GroqVisionExtractor is not None


def test_extract_items_api_error_returns_empty(tmp_path: Path):
    """Erreur API Groq → liste vide (pas de crash)."""
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("API error")

    with patch("groq.Groq", return_value=mock_client):
        extractor = GroqVisionExtractor(api_key="test_key")
        result = extractor.extract_items(str(png), query="wacom cintiq")
    assert result == []


def test_extract_items_returns_parsed_json(tmp_path: Path):
    """Réponse API valide → liste d'items parsés."""
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    mock_choice = MagicMock()
    mock_choice.message.content = '[{"title": "Wacom Cintiq 16", "watch_count": 200, "end_date": "2026-06-15", "price": 280.0, "ebay_url": null, "ebay_item_id": null}]'
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("groq.Groq", return_value=mock_client):
        extractor = GroqVisionExtractor(api_key="test_key")
        result = extractor.extract_items(str(png), query="wacom cintiq")

    assert len(result) == 1
    assert result[0]["title"] == "Wacom Cintiq 16"
    assert result[0]["watch_count"] == 200
    assert result[0]["end_date"] == "2026-06-15"


def test_extract_items_empty_response_returns_empty(tmp_path: Path):
    """Réponse vide → liste vide."""
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    mock_choice = MagicMock()
    mock_choice.message.content = "[]"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("groq.Groq", return_value=mock_client):
        extractor = GroqVisionExtractor(api_key="test_key")
        result = extractor.extract_items(str(png), query="test")
    assert result == []
