"""Tests for CamoufoxRunner (Stealth S2). Browser fully mocked — no real launch."""

from __future__ import annotations

import pytest

from tools.camoufox_runner import run_camoufox as rc
from tools.camoufox_runner.run_camoufox import CamoufoxRunner


# --- Fake Camoufox browser chain -------------------------------------------

class _FakeResp:
    def __init__(self, status: int):
        self.status = status


class _FakeContext:
    def __init__(self, html, cookies, status, url):
        self._html = html
        self._cookies = cookies
        self._status = status
        self._url = url

    def new_page(self):
        return _FakePage(self, self._html, self._status, self._url)

    def cookies(self):
        return self._cookies


class _FakePage:
    def __init__(self, context, html, status, url):
        self.context = context
        self._html = html
        self._status = status
        self.url = url

    def goto(self, url, **kwargs):
        return _FakeResp(self._status)

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, *args, **kwargs):
        pass

    def content(self):
        return self._html


class _FakeBrowser:
    def __init__(self, html, cookies, status, url):
        self._args = (html, cookies, status, url)

    def new_context(self, **kwargs):
        return _FakeContext(*self._args)


def _fake_camoufox_factory(html, cookies=None, status=200, url="https://example.com/final"):
    cookies = cookies if cookies is not None else [{"name": "sess"}]

    class _FakeCM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return _FakeBrowser(html, cookies, status, url)

        def __exit__(self, *args):
            return False

    return _FakeCM


_SAMPLE_HTML = (
    "<html><head><style>.x{}</style></head><body>"
    "<script>var evil=1;</script>"
    "<p>Bonjour le monde</p>"
    "</body></html>"
)


@pytest.fixture
def mocked_runner(monkeypatch):
    monkeypatch.setattr(rc, "Camoufox", _fake_camoufox_factory(_SAMPLE_HTML))
    # avoid the real sleep delay in fetch()
    monkeypatch.setattr(rc.time, "sleep", lambda *a, **k: None)
    return CamoufoxRunner()


def test_fetch_returns_all_fields(mocked_runner):
    result = mocked_runner.fetch("https://example.com", wait_ms=0)
    for field in (
        "url", "final_url", "http_status", "html", "html_len",
        "markdown", "markdown_len", "cookies", "duration_ms", "tool",
    ):
        assert field in result, f"missing field: {field}"
    assert result["tool"] == "camoufox"


def test_http_status_present(mocked_runner):
    result = mocked_runner.fetch("https://example.com", wait_ms=0)
    assert result["http_status"] == 200


def test_html_len_positive_on_success(mocked_runner):
    result = mocked_runner.fetch("https://example.com", wait_ms=0)
    assert result["html_len"] > 0


def test_markdown_len_positive_on_success(mocked_runner):
    result = mocked_runner.fetch("https://example.com", wait_ms=0)
    assert result["markdown_len"] > 0


def test_html_to_markdown_strips_scripts():
    r = CamoufoxRunner()
    md = r._html_to_markdown(_SAMPLE_HTML)
    assert "evil" not in md
    assert "var" not in md
    assert "Bonjour le monde" in md


def test_build_proxy_none_without_config():
    r = CamoufoxRunner()
    assert r._build_proxy(None) is None
    assert r._build_proxy({}) is None


def test_build_proxy_dict_with_config(monkeypatch):
    class _S:
        brightdata_username = "brd-customer-x-zone-resi"
        brightdata_password = "secret"
        brightdata_host = "brd.superproxy.io"
        brightdata_port = 33335

    monkeypatch.setattr("bridge.config.get_settings", lambda: _S())
    r = CamoufoxRunner()
    proxy = r._build_proxy({"country": "BE"})
    assert proxy["server"] == "http://brd.superproxy.io:33335"
    assert proxy["username"].endswith("-country-be")
    assert proxy["password"] == "secret"


def test_fetch_returns_error_on_exception(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("launch failed")

    monkeypatch.setattr(rc, "Camoufox", _boom)
    monkeypatch.setattr(rc.time, "sleep", lambda *a, **k: None)
    r = CamoufoxRunner()
    result = r.fetch("https://example.com", wait_ms=0)
    assert "error" in result
    assert result["tool"] == "camoufox"
    assert "launch failed" in result["error"]
