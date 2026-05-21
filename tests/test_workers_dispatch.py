"""Integration tests for bridge.workers dispatch_job subprocess wiring.

Validates that dispatch_job("scrapy", ...) routes through _run_scrapy_subprocess
which calls subprocess.run with the exact CLI contract expected by
tools.scrapy_runner.run_scrapy.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from bridge.workers import dispatch_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(returncode: int = 0, stdout: str = '{"tool":"scrapy","http_status":200}', stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# Test 1 — happy path: subprocess called with correct args, result returned
# ---------------------------------------------------------------------------

def test_dispatch_scrapy_invokes_subprocess(isolated_settings):
    with patch("bridge.workers.subprocess.run") as run:
        run.return_value = _mock_proc(stdout='{"tool":"scrapy","http_status":200,"items":[]}')
        result = dispatch_job("job_abc", "scrapy", "https://example.com", {"spider": "api_json"})

    assert result == {"tool": "scrapy", "http_status": 200, "items": []}

    args, kwargs = run.call_args
    cmd = args[0]
    # first element is sys.executable (may vary), rest must be exact
    assert cmd[1:] == ["-m", "tools.scrapy_runner.run_scrapy"]
    assert kwargs["timeout"] == 600
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True

    payload = json.loads(kwargs["input"])
    assert payload == {
        "tool": "scrapy",
        "url": "https://example.com",
        "config": {"spider": "api_json"},
        "job_id": "job_abc",
    }


# ---------------------------------------------------------------------------
# Test 2 — non-zero exit code propagates RuntimeError + audit log
# ---------------------------------------------------------------------------

def test_dispatch_scrapy_subprocess_failure_propagates(isolated_settings):
    with patch("bridge.workers.subprocess.run") as run:
        run.return_value = _mock_proc(returncode=2, stderr='{"error":"url_required"}')
        with pytest.raises(RuntimeError, match="scrapy runner exited 2"):
            dispatch_job("job_xyz", "scrapy", None, {})


# ---------------------------------------------------------------------------
# Test 3 — TimeoutExpired propagates and emits audit job_failed
# ---------------------------------------------------------------------------

def test_dispatch_scrapy_timeout_propagates(isolated_settings):
    with patch("bridge.workers.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="...", timeout=600)
        with pytest.raises(subprocess.TimeoutExpired):
            dispatch_job("job_t", "scrapy", "https://example.com", {})


# ---------------------------------------------------------------------------
# Test 4 — returncode 0 but empty stdout → RuntimeError
# ---------------------------------------------------------------------------

def test_dispatch_scrapy_empty_stdout_raises(isolated_settings):
    with patch("bridge.workers.subprocess.run") as run:
        run.return_value = _mock_proc(returncode=0, stdout="")
        with pytest.raises(RuntimeError, match="empty stdout"):
            dispatch_job("job_empty", "scrapy", "https://example.com", {})


# ---------------------------------------------------------------------------
# Test 5 — returncode 0 but stdout is not valid JSON → RuntimeError
# ---------------------------------------------------------------------------

def test_dispatch_scrapy_invalid_json_stdout_raises(isolated_settings):
    with patch("bridge.workers.subprocess.run") as run:
        run.return_value = _mock_proc(returncode=0, stdout="not json")
        with pytest.raises(RuntimeError, match="not valid JSON"):
            dispatch_job("job_badjson", "scrapy", "https://example.com", {})
