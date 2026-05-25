"""Tests for run_screenshot.main() — run() is mocked, no real browser."""
from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, patch

import pytest

_FAKE_RESULT = {
    "job_id": "abc123def456ab12",
    "tool": "screenshot",
    "url": "https://example.com",
    "final_url": "https://example.com",
    "screenshot_path": "/tmp/storage/screenshots/abc123def456ab12.png",
    "screenshot_size_kb": 24.0,
    "viewport": {"w": 1920, "h": 1080},
    "cookies_count": 5,
    "title": "Example Domain",
    "html_len": 2048,
    "profile_id": "default",
    "proxy_used": False,
    "proxy_country": None,
    "stealth_seed": 1234,
    "ts": "2026-05-24T12:00:00+00:00",
}


def _call_main(payload: dict) -> tuple[str, int]:
    """Run main() with payload on stdin; return (stdout_text, exit_code)."""
    import tools.screenshot_runner.run_screenshot as m

    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
         patch("sys.stdout", captured):
        try:
            m.main()
            return captured.getvalue(), 0
        except SystemExit as exc:
            return captured.getvalue(), int(exc.code or 0)


def test_valid_url_returns_zero_exit():
    import tools.screenshot_runner.run_screenshot as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_RESULT)):
        _, code = _call_main({"url": "https://example.com"})
    assert code == 0


def test_valid_url_produces_json_on_stdout():
    import tools.screenshot_runner.run_screenshot as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_RESULT)):
        out, _ = _call_main({"url": "https://example.com"})
    result = json.loads(out)
    assert result["job_id"] == "abc123def456ab12"


def test_required_fields_present():
    import tools.screenshot_runner.run_screenshot as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_RESULT)):
        out, _ = _call_main({"url": "https://example.com"})
    result = json.loads(out)
    for field in ("job_id", "screenshot_path", "cookies_count", "proxy_used"):
        assert field in result, f"Missing required field: {field}"


def test_tool_field_is_screenshot():
    import tools.screenshot_runner.run_screenshot as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_RESULT)):
        out, _ = _call_main({"url": "https://example.com"})
    assert json.loads(out)["tool"] == "screenshot"


def test_proxy_used_is_bool():
    import tools.screenshot_runner.run_screenshot as m
    with patch.object(m, "run", new=AsyncMock(return_value=_FAKE_RESULT)):
        out, _ = _call_main({"url": "https://example.com"})
    assert isinstance(json.loads(out)["proxy_used"], bool)


def test_missing_url_exits_2():
    _, code = _call_main({})
    assert code == 2


def test_empty_url_exits_2():
    _, code = _call_main({"url": ""})
    assert code == 2


def test_proxy_country_forwarded_to_run():
    """Ensure proxy_country in payload is passed through to run()."""
    import tools.screenshot_runner.run_screenshot as m
    proxy_result = {**_FAKE_RESULT, "proxy_used": True, "proxy_country": "BE"}
    mock_run = AsyncMock(return_value=proxy_result)
    with patch.object(m, "run", new=mock_run):
        out, code = _call_main({"url": "https://example.com", "proxy_country": "BE"})
    assert code == 0
    # Verify run() was called with the full payload including proxy_country
    call_payload = mock_run.call_args[0][0]
    assert call_payload["proxy_country"] == "BE"
