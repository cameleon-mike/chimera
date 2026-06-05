"""Tests for scripts/scrape_cron.py — all HTTP mocked, no real calls."""

import sys
import os
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.scrape_cron import scrape_once, _get_config  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_aggregate_mock(product: str) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "total_items": 42,
        "sources": {"ebay": 42, "2ememain": 0},
        "items": [],
    }
    return mock


def _build_config(monkeypatch, products=None) -> dict:
    monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("BRIDGE_BASE_URL", "http://127.0.0.1:8080")
    if products is not None:
        monkeypatch.setenv("SCRAPE_PRODUCTS", ",".join(products))
    return _get_config()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestScrapeCron:

    def test_scrape_once_returns_dict(self, monkeypatch):
        """scrape_once() returns dict keyed by product name."""
        config = _build_config(monkeypatch, products=["wacom cintiq 16", "gopro hero"])
        with patch("requests.get", side_effect=lambda url, **kw: _make_aggregate_mock(url)), \
             patch("time.sleep"):
            result = scrape_once(config)
        assert isinstance(result, dict)
        assert "wacom cintiq 16" in result
        assert "gopro hero" in result

    def test_pause_between_products(self, monkeypatch):
        """time.sleep called (n_products - 1) times with 30 as arg during scrape_once."""
        products = ["wacom cintiq 16", "gopro hero", "steelseries apex pro tkl"]
        config = _build_config(monkeypatch, products=products)
        with patch("requests.get", side_effect=lambda url, **kw: _make_aggregate_mock(url)), \
             patch("time.sleep") as mock_sleep:
            scrape_once(config)
        # Should sleep between products: n-1 = 2 times
        assert mock_sleep.call_count == len(products) - 1
        for c in mock_sleep.call_args_list:
            assert c == call(30)

    def test_config_from_env(self, monkeypatch):
        """SCRAPE_INTERVAL_MINUTES and SCRAPE_PRODUCTS read from env vars."""
        monkeypatch.setenv("BRIDGE_AUTH_TOKEN", "tok")
        monkeypatch.setenv("SCRAPE_INTERVAL_MINUTES", "120")
        monkeypatch.setenv("SCRAPE_PRODUCTS", "product a,product b")
        monkeypatch.setenv("SCRAPE_MARKETPLACE", "EBAY_BE")
        config = _get_config()
        assert config["interval"] == 120
        assert config["products"] == ["product a", "product b"]
        assert config["marketplace"] == "EBAY_BE"

    def test_log_format(self, monkeypatch, capsys):
        """output contains product name and total_items."""
        config = _build_config(monkeypatch, products=["wacom cintiq 16"])
        with patch("requests.get", side_effect=lambda url, **kw: _make_aggregate_mock(url)), \
             patch("time.sleep"):
            scrape_once(config)
        captured = capsys.readouterr()
        assert "wacom cintiq 16" in captured.out
        assert "42" in captured.out

    def test_error_handling(self, monkeypatch, capsys):
        """If requests.get raises ConnectionError, scrape_once() does not raise, logs error, continues."""
        products = ["wacom cintiq 16", "gopro hero"]
        config = _build_config(monkeypatch, products=products)

        def raise_connection_error(url, **kwargs):
            raise ConnectionError("Connection refused")

        with patch("requests.get", side_effect=raise_connection_error), \
             patch("time.sleep"):
            # Must not raise
            result = scrape_once(config)

        captured = capsys.readouterr()
        assert "ERROR" in captured.out
        # Both products should still appear in results (with zeroed values)
        assert "wacom cintiq 16" in result
        assert "gopro hero" in result
