"""Tests for tools.waf_bypass.run_bypass.

All HTTP calls are mocked — no real FlareSolverr needed.
Covers: happy path, error paths, payload forwarding, bridge dispatch wiring.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

import tools.waf_bypass.run_bypass as m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flare_response(
    html: str = "<html>OK</html>",
    status: int = 200,
    cookies: list | None = None,
    user_agent: str = "Mozilla/5.0",
    flare_status: str = "ok",
    url: str = "https://example.com",
) -> MagicMock:
    """Build a mock httpx.Response that looks like a FlareSolverr reply."""
    if cookies is None:
        cookies = []
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = {
        "status": flare_status,
        "solution": {
            "url": url,
            "status": status,
            "response": html,
            "cookies": cookies,
            "userAgent": user_agent,
        },
    }
    return resp


def _call_main(payload: dict) -> tuple[str, str, int]:
    """Invoke main() with payload on stdin; return (stdout, stderr, exit_code)."""
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", captured_out),
        patch("sys.stderr", captured_err),
    ):
        try:
            m.main()
            return captured_out.getvalue(), captured_err.getvalue(), 0
        except SystemExit as exc:
            return captured_out.getvalue(), captured_err.getvalue(), int(exc.code or 0)


# ---------------------------------------------------------------------------
# 1. test_success_with_cf_clearance
# ---------------------------------------------------------------------------

def test_success_with_cf_clearance():
    cookies = [
        {"name": "cf_clearance", "value": "abc123xyz"},
        {"name": "session", "value": "sess99"},
    ]
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response(cookies=cookies)
        out, _, code = _call_main({"url": "https://example.com", "job_id": "j1"})

    assert code == 0
    result = json.loads(out)
    assert result["tool"] == "bypass_waf"
    assert result["cf_clearance"] == "abc123xyz"
    assert result["http_status"] == 200
    assert result["job_id"] == "j1"


# ---------------------------------------------------------------------------
# 2. test_flaresolverr_down_exit3
# ---------------------------------------------------------------------------

def test_flaresolverr_down_exit3():
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.ConnectError("connection refused")
        _, err, code = _call_main({"url": "https://example.com"})

    assert code == 3
    err_data = json.loads(err.strip())
    assert "FlareSolverr not running" in err_data["error"]
    assert "suggestion" in err_data


# ---------------------------------------------------------------------------
# 3. test_missing_url_exit2
# ---------------------------------------------------------------------------

def test_missing_url_exit2():
    _, err, code = _call_main({})
    assert code == 2
    err_data = json.loads(err.strip())
    assert "missing url" in err_data["error"]


# ---------------------------------------------------------------------------
# 4. test_session_id_transmitted
# ---------------------------------------------------------------------------

def test_session_id_transmitted():
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response()
        _call_main({"url": "https://example.com", "session_id": "sess-42"})

    _, kwargs = client.post.call_args
    assert kwargs["json"]["session"] == "sess-42"


# ---------------------------------------------------------------------------
# 5. test_cf_clearance_none_when_no_cookies
# ---------------------------------------------------------------------------

def test_cf_clearance_none_when_no_cookies():
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response(cookies=[])
        out, _, code = _call_main({"url": "https://example.com"})

    assert code == 0
    result = json.loads(out)
    assert result["cf_clearance"] is None
    assert result["cookies"] == []


# ---------------------------------------------------------------------------
# 6. test_html_len_calculated
# ---------------------------------------------------------------------------

def test_html_len_calculated():
    html = "<html><body>Hello World</body></html>"
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response(html=html)
        out, _, code = _call_main({"url": "https://example.com"})

    assert code == 0
    result = json.loads(out)
    assert result["html"] == html
    assert result["html_len"] == len(html)


# ---------------------------------------------------------------------------
# 7. test_custom_flaresolverr_url
# ---------------------------------------------------------------------------

def test_custom_flaresolverr_url():
    custom_url = "http://flare.internal:9999/v1"
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response()
        _call_main({"url": "https://example.com", "flaresolverr_url": custom_url})

    positional_args, _ = client.post.call_args
    assert positional_args[0] == custom_url


# ---------------------------------------------------------------------------
# 8. test_max_timeout_transmitted
# ---------------------------------------------------------------------------

def test_max_timeout_transmitted():
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response()
        _call_main({"url": "https://example.com", "max_timeout": 30000})

    _, kwargs = client.post.call_args
    assert kwargs["json"]["maxTimeout"] == 30000


# ---------------------------------------------------------------------------
# 9. test_bridge_dispatch_bypass_waf
# ---------------------------------------------------------------------------

def test_bridge_dispatch_bypass_waf():
    from bridge.workers import _DISPATCH, _run_bypass_subprocess

    assert _DISPATCH["bypass_waf"] is _run_bypass_subprocess


# ---------------------------------------------------------------------------
# 10. test_job_id_propagated
# ---------------------------------------------------------------------------

def test_job_id_propagated():
    with patch("httpx.Client") as mock_cls:
        client = mock_cls.return_value.__enter__.return_value
        client.post.return_value = _flare_response()
        out, _, code = _call_main({"url": "https://example.com", "job_id": "test-123"})

    assert code == 0
    result = json.loads(out)
    assert result["job_id"] == "test-123"
