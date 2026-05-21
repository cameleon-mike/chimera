"""Tests for the spiders, middlewares, and pipeline of the Scrapy runner.

These are unit-level tests that do NOT spawn a real Twisted reactor — they
instantiate the spider/middleware/pipeline classes directly and exercise
their parse / process_request / process_item methods with fake responses.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import scrapy
from scrapy.http import HtmlResponse, Request, TextResponse

from tools.scrapy_runner.project.middlewares.human_delay import HumanDelayMiddleware
from tools.scrapy_runner.project.middlewares.rotate_ua import (
    RotateUserAgentMiddleware,
    _FALLBACK_UAS,
)
from tools.scrapy_runner.project.pipelines import CollectorPipeline
from tools.scrapy_runner.project.spiders.adaptive import AdaptiveSpider
from tools.scrapy_runner.project.spiders.api_json import ApiJsonSpider


def _make_text_response(url: str, body: str, status: int = 200) -> TextResponse:
    req = Request(url=url)
    return TextResponse(
        url=url, body=body.encode("utf-8"), status=status, request=req, encoding="utf-8"
    )


def _make_html_response(url: str, body: str, status: int = 200) -> HtmlResponse:
    req = Request(url=url)
    return HtmlResponse(
        url=url, body=body.encode("utf-8"), status=status, request=req, encoding="utf-8"
    )


# ---------- ApiJsonSpider ----------------------------------------------

class TestApiJsonSpider:
    def test_init_defaults(self):
        sp = ApiJsonSpider()
        assert sp.start_urls == []
        assert sp.extra_headers == {}

    def test_init_with_urls_and_headers(self):
        sp = ApiJsonSpider(urls=["https://a.test"], headers={"X-Test": "1"})
        assert sp.start_urls == ["https://a.test"]
        assert sp.extra_headers == {"X-Test": "1"}

    def test_start_requests_emits_one_per_url(self):
        sp = ApiJsonSpider(urls=["https://a.test", "https://b.test"], headers={"X-K": "v"})
        reqs = list(sp.start_requests())
        assert [r.url for r in reqs] == ["https://a.test", "https://b.test"]
        assert all(r.headers.get("X-K") == b"v" for r in reqs)
        assert all(r.dont_filter for r in reqs)

    def test_parse_valid_json(self):
        sp = ApiJsonSpider()
        body = json.dumps({"hello": "world", "n": 42})
        resp = _make_text_response("https://api.test/x", body)
        items = list(sp.parse(resp))
        assert len(items) == 1
        item = items[0]
        assert item["url"] == "https://api.test/x"
        assert item["http_status"] == 200
        assert item["data"] == {"hello": "world", "n": 42}
        assert item["fetched_at"].endswith("Z")
        assert sp._final_http_status == 200

    def test_parse_invalid_json_surfaces_raw(self):
        sp = ApiJsonSpider()
        resp = _make_text_response("https://api.test/x", "<html>not json</html>")
        items = list(sp.parse(resp))
        assert items[0]["data"]["_parse_error"] == "not_json"
        assert "<html>" in items[0]["data"]["_raw"]

    def test_parse_records_status(self):
        sp = ApiJsonSpider()
        resp = _make_text_response("https://api.test/x", "{}", status=418)
        list(sp.parse(resp))
        assert sp._final_http_status == 418


# ---------- AdaptiveSpider ---------------------------------------------

class TestAdaptiveSpider:
    def test_init_defaults(self):
        sp = AdaptiveSpider()
        assert sp.start_urls == []
        assert sp.selectors == {}
        assert sp.item_selector is None
        assert sp.extra_headers == {}

    def test_parse_single_item(self):
        sp = AdaptiveSpider(selectors={"title": "h1::text"})
        resp = _make_html_response(
            "https://x.test", "<html><body><h1>Hello</h1></body></html>"
        )
        items = list(sp.parse(resp))
        assert len(items) == 1
        assert items[0]["title"] == "Hello"
        assert items[0]["url"] == "https://x.test"
        assert sp._final_http_status == 200

    def test_parse_with_item_selector_yields_many(self):
        sp = AdaptiveSpider(
            selectors={"name": "span::text"},
            item_selector="li.item",
        )
        html = """
        <ul>
          <li class="item"><span>alpha</span></li>
          <li class="item"><span>beta</span></li>
          <li class="item"><span>gamma</span></li>
        </ul>
        """
        resp = _make_html_response("https://x.test", html)
        items = list(sp.parse(resp))
        assert [i["name"] for i in items] == ["alpha", "beta", "gamma"]
        assert all(i["url"] == "https://x.test" for i in items)

    def test_extract_one_collapses_single_value(self):
        sp = AdaptiveSpider(selectors={"t": "h1::text"})
        resp = _make_html_response("https://x.test", "<h1>Single</h1>")
        items = list(sp.parse(resp))
        assert items[0]["t"] == "Single"  # not a list

    def test_extract_one_keeps_list_when_many(self):
        sp = AdaptiveSpider(selectors={"links": "a::attr(href)"})
        resp = _make_html_response(
            "https://x.test",
            '<a href="/a">a</a><a href="/b">b</a>',
        )
        items = list(sp.parse(resp))
        assert items[0]["links"] == ["/a", "/b"]


# ---------- CollectorPipeline ------------------------------------------

class TestCollectorPipeline:
    def test_open_spider_initializes_state(self):
        pipe = CollectorPipeline()
        spider = SimpleNamespace()
        pipe.open_spider(spider)
        assert spider._collected_items == []
        assert spider._final_http_status is None

    def test_process_item_collects_dict(self):
        pipe = CollectorPipeline()
        spider = SimpleNamespace()
        pipe.open_spider(spider)
        item = {"k": "v"}
        out = pipe.process_item(item, spider)
        assert out is item
        assert spider._collected_items == [{"k": "v"}]

    def test_process_item_coerces_scrapy_item(self):
        class Demo(scrapy.Item):
            url = scrapy.Field()

        pipe = CollectorPipeline()
        spider = SimpleNamespace()
        pipe.open_spider(spider)
        pipe.process_item(Demo(url="https://x.test"), spider)
        assert spider._collected_items == [{"url": "https://x.test"}]

    def test_multiple_items_preserve_order(self):
        pipe = CollectorPipeline()
        spider = SimpleNamespace()
        pipe.open_spider(spider)
        for i in range(3):
            pipe.process_item({"i": i}, spider)
        assert spider._collected_items == [{"i": 0}, {"i": 1}, {"i": 2}]


# ---------- RotateUserAgentMiddleware ----------------------------------

class TestRotateUserAgentMiddleware:
    def test_sets_ua_when_absent(self):
        mw = RotateUserAgentMiddleware()
        req = Request("https://x.test")
        mw.process_request(req, spider=None)
        assert req.headers.get("User-Agent") is not None
        # Should be a real-looking UA string.
        ua = req.headers["User-Agent"].decode("utf-8")
        assert "Mozilla" in ua or "Chrome" in ua or "Firefox" in ua or "Safari" in ua

    def test_preserves_existing_ua(self):
        mw = RotateUserAgentMiddleware()
        req = Request("https://x.test", headers={"User-Agent": "custom/1.0"})
        mw.process_request(req, spider=None)
        assert req.headers["User-Agent"] == b"custom/1.0"

    def test_fallback_pool_is_populated(self):
        assert len(_FALLBACK_UAS) >= 5
        assert all("Mozilla" in ua for ua in _FALLBACK_UAS)


# ---------- HumanDelayMiddleware ---------------------------------------

class TestHumanDelayMiddleware:
    def test_from_crawler_reads_settings(self):
        crawler = SimpleNamespace(
            settings=SimpleNamespace(
                getfloat=lambda k, default: {"HUMAN_DELAY_MEAN": 0.7, "HUMAN_DELAY_JITTER": 0.3}.get(k, default)
            )
        )
        mw = HumanDelayMiddleware.from_crawler(crawler)
        assert mw.mean == 0.7
        assert mw.jitter == 0.3

    def test_process_request_sleeps_and_returns_none(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(
            "tools.scrapy_runner.project.middlewares.human_delay.time.sleep",
            lambda d: slept.append(d),
        )
        # Force a deterministic delay
        monkeypatch.setattr(
            "tools.scrapy_runner.project.middlewares.human_delay.random.lognormvariate",
            lambda mu, sigma: 0.25,
        )
        mw = HumanDelayMiddleware(mean=0.4, jitter=0.5)
        out = mw.process_request(Request("https://x.test"), spider=None)
        assert out is None
        assert slept == [0.25]

    def test_delay_is_capped_at_4_seconds(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(
            "tools.scrapy_runner.project.middlewares.human_delay.time.sleep",
            lambda d: slept.append(d),
        )
        monkeypatch.setattr(
            "tools.scrapy_runner.project.middlewares.human_delay.random.lognormvariate",
            lambda mu, sigma: 10.0,  # would be 10s without cap
        )
        mw = HumanDelayMiddleware()
        mw.process_request(Request("https://x.test"), spider=None)
        assert slept == [4.0]

    def test_delay_floored_at_zero(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(
            "tools.scrapy_runner.project.middlewares.human_delay.time.sleep",
            lambda d: slept.append(d),
        )
        monkeypatch.setattr(
            "tools.scrapy_runner.project.middlewares.human_delay.random.lognormvariate",
            lambda mu, sigma: -1.0,  # would be negative without floor
        )
        mw = HumanDelayMiddleware()
        mw.process_request(Request("https://x.test"), spider=None)
        assert slept == [0.0]
