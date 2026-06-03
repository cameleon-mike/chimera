"""Tests pour UniversalExtractor."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.extractors.universal_extractor import UniversalExtractor

SCHEMA_PATH = str(Path(__file__).parents[1] / "tools/extractors/schemas/vinted_fr.json")


def make_extractor(groq_api_key: str = "") -> UniversalExtractor:
    return UniversalExtractor(schema_path=SCHEMA_PATH, groq_api_key=groq_api_key)


# HTML fixtures
VALID_HTML = """
<html><body>
<div data-testid="item-card">
  <a href="/items/123456789-wacom-intuos">
    <span data-testid="item-title">Wacom Intuos Pro M</span>
    <div data-testid="item-price"><span>85,00 €</span></div>
    <span data-testid="item-brand">Wacom</span>
    <span data-testid="item-size">M</span>
    <span data-testid="item-condition">Très bon état</span>
    <img src="https://images.vinted.net/123.jpg" />
  </a>
</div>
</body></html>
"""

INVALID_SELECTOR_HTML = "<html><body><p>Aucun article</p></body></html>"


# --- _css_extract ---

def test_css_extract_valid_html():
    """CSS extract retourne items si sélecteur valide."""
    ex = make_extractor()
    items = ex._css_extract(VALID_HTML)
    assert len(items) >= 1


def test_css_extract_invalid_html():
    """CSS extract retourne [] si aucun sélecteur ne matche."""
    ex = make_extractor()
    items = ex._css_extract(INVALID_SELECTOR_HTML)
    assert items == []


def test_css_extract_title():
    """Title correctement extrait."""
    ex = make_extractor()
    items = ex._css_extract(VALID_HTML)
    assert items[0]["title"] == "Wacom Intuos Pro M"


def test_css_extract_url():
    """URL correctement extraite."""
    ex = make_extractor()
    items = ex._css_extract(VALID_HTML)
    assert "/items/123456789" in items[0]["url"]


# --- _llm_extract ---

def test_llm_extract_valid_json():
    """_llm_extract parse un JSON array valide."""
    ex = make_extractor(groq_api_key="fake-key")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = json.dumps([
        {"title": "Wacom", "price_raw": "85,00 €", "url": "/items/1", "photo_url": "https://img.net/1.jpg"}
    ])
    with patch("tools.extractors.universal_extractor.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.return_value = mock_resp
        items = ex._llm_extract("# Wacom listings\n- Wacom 85€")
    assert len(items) >= 1


def test_llm_extract_invalid_json_no_exception():
    """_llm_extract retourne [] si JSON invalide — jamais d'exception."""
    ex = make_extractor(groq_api_key="fake-key")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "pas du JSON { malformé"
    with patch("tools.extractors.universal_extractor.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.return_value = mock_resp
        items = ex._llm_extract("some markdown")
    assert items == []


def test_llm_extract_no_key_returns_empty():
    """Sans groq_api_key → retourne [] immédiatement."""
    ex = make_extractor(groq_api_key="")
    items = ex._llm_extract("some markdown")
    assert items == []


def test_llm_extract_groq_down_returns_empty():
    """Groq down (exception réseau) → retourne [] sans exception."""
    ex = make_extractor(groq_api_key="fake-key")
    with patch("tools.extractors.universal_extractor.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.side_effect = RuntimeError("API down")
        items = ex._llm_extract("some markdown")
    assert items == []


# --- _normalize_price ---

def test_normalize_price_french_format():
    """'25,00 €' → 25.0"""
    ex = make_extractor()
    assert ex._normalize_price("25,00 €") == pytest.approx(25.0)


def test_normalize_price_dot_decimal():
    """'25.00' → 25.0"""
    ex = make_extractor()
    assert ex._normalize_price("25.00") == pytest.approx(25.0)


def test_normalize_price_unparseable():
    """Non-parseable → None"""
    ex = make_extractor()
    assert ex._normalize_price("gratuit") is None


# --- _normalize_condition ---

def test_normalize_condition_all_cases():
    """Tous les cas de condition."""
    ex = make_extractor()
    assert ex._normalize_condition("Neuf avec étiquette") == "new_with_tags"
    assert ex._normalize_condition("Très bon état") == "very_good"
    assert ex._normalize_condition("Bon état") == "good"
    assert ex._normalize_condition("Satisfaisant") == "satisfactory"
    assert ex._normalize_condition("Inconnu") == "unknown"


# --- _normalize_date ---

def test_normalize_date_today_fr():
    """'Aujourd'hui' → ISO date du jour."""
    ex = make_extractor()
    assert ex._normalize_date("Aujourd'hui") == date.today().strftime("%Y-%m-%d")


def test_normalize_date_yesterday_fr():
    """'Hier' → ISO date d'hier."""
    ex = make_extractor()
    expected = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert ex._normalize_date("Hier") == expected


# --- extract (cascade) ---

def test_extract_css_success_llm_not_called():
    """Niveau 1 CSS réussit → LLM non appelé."""
    ex = make_extractor(groq_api_key="fake-key")
    with patch.object(ex, "_llm_extract") as mock_llm:
        # _css_extract returns valid items, so LLM should not be called
        with patch.object(ex, "_css_extract", return_value=[
            {"title": "Wacom", "price_eur": 85.0, "url": "/items/1"}
        ]):
            ex.extract(VALID_HTML)
        mock_llm.assert_not_called()


def test_extract_css_fails_llm_called():
    """Niveau 1 CSS échoue → Niveau 2 LLM appelé."""
    ex = make_extractor(groq_api_key="fake-key")
    with patch.object(ex, "_css_extract", return_value=[]):
        with patch.object(ex, "_llm_extract", return_value=[]) as mock_llm:
            ex.extract(INVALID_SELECTOR_HTML, markdown="some markdown")
        mock_llm.assert_called_once()
