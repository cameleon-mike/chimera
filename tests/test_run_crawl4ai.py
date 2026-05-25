"""Tests for run_crawl4ai.main() — run() is mocked, no real browser."""
from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, patch

import pytest

_FAKE_MARKDOWN_RESULT = {
    "job_id": "aa11bb22cc33dd44",
    "tool": "crawl4ai",
    "url": "http://books.toscrape.com",
    "final_url": "http://books.toscrape.com",
    "http_status": 200,
    "success": True,
    "mode": "markdown",
    "proxy": None,
    "html_len": 51200,
    "title": "All products | Books to Scrape",
    "markdown": "# All products\n\nFifty books listed.",
    "markdown_len": 36,
    "ts": "2026-05-24T10:00:00+00:00",
}

_FAKE_EXTRACT_RESULT = {
    "job_id": "ee55ff66aa77bb88",
    "tool": "crawl4ai",
    "url": "http://books.toscrape.com",
    "final_url": "http://books.toscrape.com",
    "http_status": 200,
    "success": True,
    "mode": "extract",
    "proxy": None,
    "html_len": 51200,
    "title": "All products | Books to Scrape",
    "extracted": [{"title": "A Light in the Attic", "price": "£51.77", "rating": "star-rating Three"}],
    "items_count": 1,
    "ts": "2026-05-24T10:00:00+00:00",
}

_FAKE_FAILED_RESULT = {
    "job_id": "cc99dd00ee11ff22",
    "tool": "crawl4ai",
    "url": "http://unreachable.example.invalid",
    "final_url": "http://unreachable.example.invalid",
    "http_status": 0,
    "success": False,
    "mode": "markdown",
    "proxy": None,
    "html_len": 0,
    "title": "",
    "error": "connection refused",
    "ts": "2026-05-24T10:00:00+00:00",
}


def _call_main(payload: dict) -> tuple[str, int]:
    """Run main() with payload on stdin; return (stdout_text, exit_code)."""
    import tools.crawl4ai_runner.run_crawl4ai as m

    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
         patch("sys.stdout", captured):
        try:
            m.main()
            return captured.getvalue(), 0
        except SystemExit as exc:
            return captured.getvalue(), int(exc.code or 0)


# --- Happy paths ---


def test_markdown_mode_returns_zero_exit():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_MARKDOWN_RESULT)):
        _, code = _call_main({"url": "http://books.toscrape.com"})
    assert code == 0


def test_markdown_mode_stdout_is_valid_json():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_MARKDOWN_RESULT)):
        out, _ = _call_main({"url": "http://books.toscrape.com"})
    data = json.loads(out)
    assert data["mode"] == "markdown"
    assert "markdown" in data


def test_extract_mode_returns_items():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_EXTRACT_RESULT)):
        out, code = _call_main({
            "url": "http://books.toscrape.com",
            "schema": {"name": "Books", "baseSelector": "article.product_pod", "fields": []},
        })
    assert code == 0
    data = json.loads(out)
    assert data["mode"] == "extract"
    assert isinstance(data["extracted"], list)
    assert data["items_count"] == 1


def test_failed_crawl_still_zero_exit():
    """A crawl4ai success=False is a valid result — not a process error."""
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_FAILED_RESULT)):
        out, code = _call_main({"url": "http://unreachable.example.invalid"})
    assert code == 0
    data = json.loads(out)
    assert data["success"] is False
    assert "error" in data


# --- Validation errors ---


def test_missing_url_exits_2():
    _, code = _call_main({})
    assert code == 2


def test_empty_url_exits_2():
    _, code = _call_main({"url": ""})
    assert code == 2


# --- Runtime error → exit 3 ---


def test_runtime_exception_exits_3():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(side_effect=RuntimeError("browser crash"))):
        _, code = _call_main({"url": "http://books.toscrape.com"})
    assert code == 3


# --- Result shape ---


def test_result_contains_mandatory_fields():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_MARKDOWN_RESULT)):
        out, _ = _call_main({"url": "http://books.toscrape.com"})
    data = json.loads(out)
    for field in ("job_id", "tool", "url", "final_url", "http_status", "success", "mode", "ts"):
        assert field in data, f"missing field: {field}"


def test_tool_field_is_crawl4ai():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_MARKDOWN_RESULT)):
        out, _ = _call_main({"url": "http://books.toscrape.com"})
    assert json.loads(out)["tool"] == "crawl4ai"


def test_proxy_field_none_when_not_provided():
    import tools.crawl4ai_runner.run_crawl4ai as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_MARKDOWN_RESULT)):
        out, _ = _call_main({"url": "http://books.toscrape.com"})
    assert json.loads(out)["proxy"] is None


# --- Cache mode mapping ---


def test_cache_mode_bypass_default():
    """Verify _CACHE_MODES maps 'bypass' to CacheMode.BYPASS."""
    from crawl4ai import CacheMode
    from tools.crawl4ai_runner.run_crawl4ai import _CACHE_MODES
    assert _CACHE_MODES["bypass"] is CacheMode.BYPASS


def test_cache_mode_all_keys_present():
    from tools.crawl4ai_runner.run_crawl4ai import _CACHE_MODES
    for key in ("bypass", "enabled", "disabled", "read_only", "write_only"):
        assert key in _CACHE_MODES, f"missing key: {key}"


def test_cache_mode_unknown_falls_back_to_bypass():
    """Unrecognised cache_mode silently defaults to BYPASS — pin this contract."""
    from crawl4ai import CacheMode
    from tools.crawl4ai_runner.run_crawl4ai import _CACHE_MODES
    assert _CACHE_MODES.get("nonexistent_value", CacheMode.BYPASS) is CacheMode.BYPASS


def test_session_id_in_payload_is_accepted():
    """session_id must pass through without raising — manifest contract."""
    import tools.crawl4ai_runner.run_crawl4ai as m
    result = {**_FAKE_MARKDOWN_RESULT, "job_id": "sess_test_001"}
    with patch.object(m, "run", new=AsyncMock(return_value=result)):
        out, code = _call_main({"url": "http://books.toscrape.com", "session_id": "sticky-123"})
    assert code == 0
    assert json.loads(out)["tool"] == "crawl4ai"
