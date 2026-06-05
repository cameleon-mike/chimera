"""Tests for ScrapingAgent."""
import os
import logging
from unittest.mock import MagicMock, patch, call
import pytest
from tools.scraping_agent.agent import ScrapingAgent


PRODUCTS = ["wacom cintiq 16", "gopro hero", "steelseries apex pro tkl"]


def _make_agent(**kw):
    defaults = dict(base_url="http://localhost:8080", token="tok", products=PRODUCTS)
    defaults.update(kw)
    return ScrapingAgent(**defaults)


def _agg_response(total=5, epid_count=3):
    items = [{"epid": "E1", "title": "x"} for _ in range(epid_count)]
    items += [{"epid": None, "title": "y"} for _ in range(total - epid_count)]
    return {"total_items": total, "items": items, "sources": {"ebay": total}}


def _wc_response(items_with_end_date=2, items_without=1):
    items = [{"title": "sold", "end_date": "2025-01-01", "price": 100.0, "ebay_url": "https://e.com/1", "ebay_item_id": "1"} for _ in range(items_with_end_date)]
    items += [{"title": "active", "end_date": None, "price": 80.0, "ebay_url": "https://e.com/2", "ebay_item_id": "2"} for _ in range(items_without)]
    return {"total_items": len(items), "items": items}


def _epid_search_response():
    return [{"epid": "E1", "median_price": 199.0, "avg_sell_days": 14.0}]


# Test 1
def test_run_once_returns_all_products():
    """run_once() returns dict with all 3 products."""
    agent = _make_agent()
    with patch.object(agent, "_scrape_product", return_value={"items": 5, "epids": 3, "median": 100.0, "avg_sell_days": 10.0}):
        result = agent.run_once()
    assert set(result.keys()) == set(PRODUCTS)


# Test 2
def test_scrape_product_returns_expected_fields():
    """_scrape_product() returns dict with expected fields."""
    agent = _make_agent()
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: _agg_response()),
            MagicMock(status_code=200, json=lambda: _wc_response(0, 0)),
            MagicMock(status_code=200, json=lambda: []),
        ]
        result = agent._scrape_product("wacom cintiq 16")
    assert "items" in result
    assert "epids" in result
    assert "median" in result
    assert "avg_sell_days" in result


# Test 3
def test_epid_coverage_low_logs_warning(caplog):
    """epid_coverage < 10% triggers warning log."""
    agent = _make_agent()
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: _agg_response(total=20, epid_count=1)),  # 5% coverage
            MagicMock(status_code=200, json=lambda: _wc_response(0, 0)),
            MagicMock(status_code=200, json=lambda: []),
        ]
        with caplog.at_level(logging.WARNING):
            agent._scrape_product("wacom cintiq 16")
    assert any("epid_coverage_low" in r.message for r in caplog.records)


# Test 4
def test_watchcount_end_date_triggers_ingest():
    """watchcount items with end_date trigger ingest POST."""
    agent = _make_agent()
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: _agg_response()),
            MagicMock(status_code=200, json=lambda: _wc_response(items_with_end_date=2)),
            MagicMock(status_code=200, json=lambda: []),
        ]
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ingested": 2, "epids_updated": 1})
        agent._scrape_product("wacom cintiq 16")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "/epid/ingest" in call_kwargs[0][0]


# Test 5
def test_watchcount_zero_items_no_ingest():
    """watchcount 0 items → no ingest, no error."""
    agent = _make_agent()
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: _agg_response()),
            MagicMock(status_code=200, json=lambda: {"total_items": 0, "items": []}),
            MagicMock(status_code=200, json=lambda: []),
        ]
        result = agent._scrape_product("wacom cintiq 16")
    mock_post.assert_not_called()
    assert result["items"] == 5


# Test 6
def test_scheduler_starts_without_exception():
    """scheduler starts without exception."""
    agent = _make_agent()
    mock_scheduler = MagicMock()
    with patch("apscheduler.schedulers.background.BackgroundScheduler", return_value=mock_scheduler), \
         patch("signal.signal"), \
         patch("time.sleep", side_effect=KeyboardInterrupt):
        agent.start_scheduler()
    mock_scheduler.start.assert_called_once()


# Test 7
def test_scheduler_shutdown_on_keyboard_interrupt():
    """scheduler shutdown on KeyboardInterrupt."""
    agent = _make_agent()
    mock_scheduler = MagicMock()
    with patch("apscheduler.schedulers.background.BackgroundScheduler", return_value=mock_scheduler), \
         patch("signal.signal"), \
         patch("time.sleep", side_effect=KeyboardInterrupt):
        agent.start_scheduler()
    mock_scheduler.shutdown.assert_called_once_with(wait=False)


# Test 8
def test_scrape_products_from_env(monkeypatch):
    """SCRAPE_PRODUCTS read from env."""
    monkeypatch.setenv("SCRAPE_PRODUCTS", "test product a,test product b")
    products_raw = os.environ.get("SCRAPE_PRODUCTS", "")
    products = [p.strip() for p in products_raw.split(",") if p.strip()]
    assert products == ["test product a", "test product b"]


# Test 9
def test_scrape_interval_hours_from_env(monkeypatch):
    """SCRAPE_INTERVAL_HOURS read from env."""
    monkeypatch.setenv("SCRAPE_INTERVAL_HOURS", "12")
    val = int(os.environ.get("SCRAPE_INTERVAL_HOURS", "6"))
    assert val == 12


# Test 10
def test_run_once_with_explicit_products():
    """run_once() with explicit products list."""
    agent = _make_agent()
    custom = ["custom product"]
    with patch.object(agent, "_scrape_product", return_value={"items": 1, "epids": 1, "median": None, "avg_sell_days": None}) as mock_sp:
        result = agent.run_once(products=custom)
    mock_sp.assert_called_once_with("custom product")
    assert "custom product" in result
