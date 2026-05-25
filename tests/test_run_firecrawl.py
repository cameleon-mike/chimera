"""Tests for tools.firecrawl_runner.run_firecrawl.

All HTTP calls are mocked — no real Firecrawl server needed.
Covers: scrape mode, crawl mode (with poll), error paths, CLI contract.
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

import tools.firecrawl_runner.run_firecrawl as m


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _scrape_response(
    markdown: str = "# Page\nContent here.",
    title: str = "Test Page",
    status_code: int = 200,
    success: bool = True,
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "success": success,
        "data": {
            "markdown": markdown,
            "html": "<h1>Page</h1>",
            "metadata": {
                "title": title,
                "statusCode": status_code,
                "sourceURL": "https://example.com",
            },
        },
    }
    return resp


def _crawl_start_response(crawl_id: str = "crawl-abc123") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"id": crawl_id}
    return resp


def _crawl_status_response(
    crawl_id: str = "crawl-abc123",
    status: str = "completed",
    pages: list | None = None,
) -> MagicMock:
    if pages is None:
        pages = [
            {
                "markdown": "# Home\nWelcome.",
                "metadata": {
                    "sourceURL": "https://example.com",
                    "title": "Home",
                    "statusCode": 200,
                },
            },
            {
                "markdown": "# About\nInfo.",
                "metadata": {
                    "sourceURL": "https://example.com/about",
                    "title": "About",
                    "statusCode": 200,
                },
            },
        ]
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "status": status,
        "total": len(pages),
        "completed": len(pages) if status == "completed" else 0,
        "data": pages,
    }
    return resp


def _call_main(payload: dict) -> tuple[str, int]:
    """Call main() with payload on stdin; return (stdout_text, exit_code)."""
    captured_out = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", captured_out),
    ):
        try:
            m.main()
            return captured_out.getvalue(), 0
        except SystemExit as exc:
            return captured_out.getvalue(), int(exc.code or 0)


# ---------------------------------------------------------------------------
# scrape mode — happy path
# ---------------------------------------------------------------------------

class TestScrapeMode:
    def test_returns_markdown_and_zero_exit(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            result = m.run({"url": "https://example.com"})

        assert result["tool"] == "firecrawl"
        assert result["mode"] == "scrape"
        assert result["success"] is True
        assert "markdown" in result
        assert result["markdown_len"] > 0
        assert result["http_status"] == 200
        assert result["title"] == "Test Page"
        assert "job_id" in result
        assert "ts" in result

    def test_html_format_included_when_requested(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            result = m.run({"url": "https://example.com", "formats": ["markdown", "html"]})

        assert "html" in result
        assert "html_len" in result

    def test_proxy_stored_in_result(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            result = m.run({"url": "https://example.com", "proxy": "http://proxy:8080"})

        assert result["proxy"] == "http://proxy:8080"

    def test_firecrawl_url_passed_to_request(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            m.run({"url": "https://example.com", "firecrawl_url": "http://custom:9999"})

        call_args = client.post.call_args
        assert "http://custom:9999/v1/scrape" in call_args[0][0]

    def test_auth_header_sent(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            m.run({"url": "https://example.com", "firecrawl_api_key": "my-key"})

        _, kwargs = client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer my-key"

    def test_wait_ms_sent_as_waitfor(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            m.run({"url": "https://example.com", "wait_ms": 2000})

        _, kwargs = client.post.call_args
        assert kwargs["json"]["waitFor"] == 2000

    def test_only_main_content_forwarded(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            m.run({"url": "https://example.com", "only_main_content": False})

        _, kwargs = client.post.call_args
        assert kwargs["json"]["onlyMainContent"] is False

    def test_firecrawl_success_false_adds_error_key(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response(success=False)
            result = m.run({"url": "https://example.com"})

        assert result["success"] is False
        assert "error" in result

    def test_job_id_accepted_from_payload(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _scrape_response()
            result = m.run({"url": "https://example.com", "job_id": "myspecialid"})

        assert result["job_id"] == "myspecialid"


# ---------------------------------------------------------------------------
# crawl mode — happy path
# ---------------------------------------------------------------------------

class TestCrawlMode:
    def test_returns_pages_list(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _crawl_start_response()
            client.get.return_value = _crawl_status_response()
            result = m.run({"url": "https://example.com", "mode": "crawl"})

        assert result["mode"] == "crawl"
        assert result["success"] is True
        assert result["pages_count"] == 2
        assert len(result["pages"]) == 2
        assert result["pages"][0]["url"] == "https://example.com"
        assert result["pages"][0]["markdown_len"] > 0
        assert "crawl_id" in result

    def test_crawl_limit_and_depth_forwarded(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _crawl_start_response()
            client.get.return_value = _crawl_status_response()
            m.run({"url": "https://example.com", "mode": "crawl", "max_pages": 5, "max_depth": 3})

        _, kwargs = client.post.call_args
        assert kwargs["json"]["limit"] == 5
        assert kwargs["json"]["maxDepth"] == 3

    def test_crawl_polls_until_completed(self):
        scraping_resp = _crawl_status_response(status="scraping", pages=[])
        completed_resp = _crawl_status_response(status="completed")

        with patch("httpx.Client") as mock_client_cls, patch("time.sleep"):
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _crawl_start_response()
            client.get.side_effect = [scraping_resp, scraping_resp, completed_resp]
            result = m.run({"url": "https://example.com", "mode": "crawl"})

        assert result["success"] is True
        assert client.get.call_count == 3

    def test_crawl_failed_status_raises(self):
        failed_resp = _crawl_status_response(status="failed", pages=[])
        failed_resp.json.return_value = {"status": "failed", "error": "timeout", "data": []}

        with patch("httpx.Client") as mock_client_cls, patch("time.sleep"):
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _crawl_start_response()
            client.get.return_value = failed_resp
            with pytest.raises(RuntimeError, match="failed"):
                m.run({"url": "https://example.com", "mode": "crawl"})

    def test_crawl_poll_timeout_raises(self):
        scraping_resp = _crawl_status_response(status="scraping", pages=[])

        with (
            patch("httpx.Client") as mock_client_cls,
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0.0, 999.0, 999.0, 999.0]),
        ):
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.return_value = _crawl_start_response()
            client.get.return_value = scraping_resp
            with pytest.raises(RuntimeError, match="did not complete"):
                m.run({"url": "https://example.com", "mode": "crawl", "poll_timeout_s": 1})


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_http_error_raises(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            resp = MagicMock(spec=httpx.Response)
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock()
            )
            client.post.return_value = resp
            with pytest.raises(httpx.HTTPStatusError):
                m.run({"url": "https://example.com"})

    def test_connect_error_propagates(self):
        with patch("httpx.Client") as mock_client_cls:
            client = mock_client_cls.return_value.__enter__.return_value
            client.post.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises(httpx.ConnectError):
                m.run({"url": "https://example.com"})


# ---------------------------------------------------------------------------
# CLI contract (main / exit codes)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_missing_url_exits_2(self):
        _, code = _call_main({})
        assert code == 2

    def test_success_exits_0(self):
        with patch("tools.firecrawl_runner.run_firecrawl.run") as mock_run:
            mock_run.return_value = {
                "job_id": "abc",
                "tool": "firecrawl",
                "mode": "scrape",
                "url": "https://example.com",
                "http_status": 200,
                "success": True,
                "markdown": "# Hi",
                "markdown_len": 4,
                "title": "Hi",
                "firecrawl_url": "http://127.0.0.1:3002",
                "proxy": None,
                "ts": "2026-05-24T10:00:00+00:00",
            }
            out, code = _call_main({"url": "https://example.com"})

        assert code == 0
        result = json.loads(out)
        assert result["tool"] == "firecrawl"

    def test_runtime_error_exits_3(self):
        with patch(
            "tools.firecrawl_runner.run_firecrawl.run",
            side_effect=RuntimeError("server down"),
        ):
            _, code = _call_main({"url": "https://example.com"})

        assert code == 3

    def test_output_is_valid_json(self):
        with patch("tools.firecrawl_runner.run_firecrawl.run") as mock_run:
            mock_run.return_value = {
                "job_id": "x",
                "tool": "firecrawl",
                "mode": "scrape",
                "url": "https://example.com",
                "http_status": 200,
                "success": True,
                "markdown": "",
                "markdown_len": 0,
                "title": "",
                "firecrawl_url": "http://127.0.0.1:3002",
                "proxy": None,
                "ts": "2026-05-24T10:00:00+00:00",
            }
            out, code = _call_main({"url": "https://example.com"})

        assert code == 0
        parsed = json.loads(out)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# bridge/workers subprocess wiring
# ---------------------------------------------------------------------------

class TestWorkersDispatch:
    def test_dispatch_firecrawl_invokes_subprocess(self, isolated_settings):
        import json
        import subprocess
        from unittest.mock import MagicMock, patch

        from bridge.workers import dispatch_job

        fake_result = {
            "tool": "firecrawl",
            "mode": "scrape",
            "url": "https://example.com",
            "http_status": 200,
            "success": True,
            "markdown": "# Hi",
            "markdown_len": 4,
            "title": "Hi",
            "firecrawl_url": "http://127.0.0.1:3002",
            "proxy": None,
            "ts": "2026-05-24T10:00:00",
            "job_id": "testjob",
        }

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(fake_result)
        mock_proc.stderr = ""

        with patch("bridge.workers.subprocess.run", return_value=mock_proc):
            result = dispatch_job("testjob", "firecrawl", "https://example.com", {})

        assert result["tool"] == "firecrawl"
        assert result["http_status"] == 200

    def test_dispatch_firecrawl_subprocess_failure_raises(self, isolated_settings):
        import subprocess
        from unittest.mock import MagicMock, patch

        from bridge.workers import dispatch_job

        mock_proc = MagicMock()
        mock_proc.returncode = 3
        mock_proc.stdout = ""
        mock_proc.stderr = '{"error":"connection refused"}'

        with patch("bridge.workers.subprocess.run", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="firecrawl runner exited 3"):
                dispatch_job("testjob", "firecrawl", "https://example.com", {})

    def test_dispatch_firecrawl_empty_stdout_raises(self, isolated_settings):
        from unittest.mock import MagicMock, patch

        from bridge.workers import dispatch_job

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch("bridge.workers.subprocess.run", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="empty stdout"):
                dispatch_job("testjob", "firecrawl", "https://example.com", {})
