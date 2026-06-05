"""Tests for scripts/flipmachine_e2e.py — all HTTP mocked, no real calls."""

import sys
import os
import io
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.flipmachine_e2e import main as e2e_main, PRODUITS_TEST  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers to build mock HTTP responses
# ---------------------------------------------------------------------------

def _make_aggregate_response(query: str) -> MagicMock:
    """Return a mock requests.Response for /aggregate/search."""
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()

    # Build 71 items: 14 with epid, rest with None
    items = []
    for i in range(71):
        items.append({"epid": "12028395711" if i < 14 else None, "title": f"item {i}"})

    mock.json.return_value = {
        "query": query,
        "marketplace": "EBAY_FR",
        "total_items": 71,
        "sources": {"ebay": 71, "2ememain": 0},
        "items": items,
        "duplicates_removed": 0,
        "ebay_blocked": False,
        "twoememain_blocked": False,
        "ts": "2026-06-05T00:00:00Z",
    }
    return mock


def _make_epid_stats_response() -> MagicMock:
    """Return a mock requests.Response for /epid/stats/{epid}."""
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "epid": "12028395711",
        "brand": "Wacom",
        "model": "Cintiq 16",
        "total_items": 7,
        "currency": "EUR",
        "median_price": 363.27,
        "q1_price": 300.0,
        "q2_price": 363.27,
        "q3_price": 400.0,
        "q4_price": 450.0,
        "avg_sell_days": None,
        "min_sell_days": None,
        "max_sell_days": None,
        "sell_days_sample": 0,
        "last_updated": "2026-06-05T00:00:00Z",
    }
    return mock


def _side_effect(url, **kwargs):
    """Route mock based on URL substring."""
    if "/epid/stats" in url:
        return _make_epid_stats_response()
    return _make_aggregate_response(url)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFlipMachineE2E:

    def test_e2e_returns_dict_with_all_products(self, monkeypatch):
        """main() returns dict with 3 keys matching PRODUITS_TEST queries."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        expected_keys = {p["query"] for p in PRODUITS_TEST}
        assert set(result.keys()) == expected_keys

    def test_total_items_positive(self, monkeypatch):
        """wacom result has total_items > 0."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        assert result["wacom cintiq 16"]["total_items"] > 0

    def test_epid_coverage_calculated(self, monkeypatch):
        """epid_coverage is float between 0 and 100."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        cov = result["wacom cintiq 16"]["epid_coverage"]
        assert isinstance(cov, float)
        assert 0.0 <= cov <= 100.0

    def test_median_price_extracted(self, monkeypatch):
        """median_price is float when epids found."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        wacom = result["wacom cintiq 16"]
        assert len(wacom["epids_found"]) >= 1
        assert isinstance(wacom["median_price"], float)

    def test_avg_sell_days_null_handled(self, monkeypatch):
        """avg_sell_days is None, no crash."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        assert result["wacom cintiq 16"]["avg_sell_days"] is None

    def test_success_criteria_pass(self, monkeypatch):
        """wacom result success == True."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        assert result["wacom cintiq 16"]["success"] is True

    def test_output_formatted(self, monkeypatch, capsys):
        """main() runs without exception and prints expected sections."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            e2e_main()
        captured = capsys.readouterr()
        assert "FLIPMACHINE E2E" in captured.out
        assert "wacom cintiq 16" in captured.out
        assert "RÉSULTAT" in captured.out

    def test_success_count_all_pass(self, monkeypatch):
        """All 3 products succeed in happy path."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
        with patch("requests.get", side_effect=_side_effect):
            result = e2e_main()
        passed = sum(1 for r in result.values() if r.get("success"))
        assert passed == 3
