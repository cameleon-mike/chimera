"""Tests for risk_signals.RiskMiddleware."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.scrapy_runner.project.middlewares.risk_signals import (
    RiskMiddleware,
    _compute_risk_score,
    _detect_vendors,
)


def _make_response(status=200, headers=None, body=b"<html>" + b"x" * 3000 + b"</html>"):
    """Build a minimal mock Scrapy response."""
    response = MagicMock()
    response.status = status
    response.body = body
    # Simulate response.text as decoded body
    response.text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    # Scrapy headers: dict of bytes key -> list of bytes values
    raw_headers: dict[bytes, list[bytes]] = {}
    if headers:
        for k, v in headers.items():
            raw_headers[k.encode()] = [v.encode()]
    response.headers = raw_headers
    return response


def _make_request(url="https://example.com/"):
    req = MagicMock()
    req.url = url
    req.meta = {}
    return req


def _make_spider():
    spider = MagicMock()
    spider.job_id = "testjob01"
    # crawler.stats.get_value returns None by default
    spider.crawler.stats.get_value.return_value = None
    return spider


class TestDetectVendors:
    def test_clean_response_no_vendors(self):
        vendors = _detect_vendors("Content-Type: text/html", "<html>clean</html>")
        assert vendors == {}

    def test_cloudflare_header_detected(self):
        vendors = _detect_vendors("cf-ray: 12345abc", "")
        assert "cloudflare" in vendors

    def test_captcha_body_detected(self):
        vendors = _detect_vendors("", "<form class='g-recaptcha'>please verify</form>")
        assert "captcha" in vendors

    def test_datadome_detected(self):
        vendors = _detect_vendors("x-datadome: protected", "")
        assert "datadome" in vendors


class TestComputeRiskScore:
    def test_clean_response_zero_score(self):
        score = _compute_risk_score(200, {}, {"waf": 0, "captcha": 0, "botdet": 0, "status": 0}, 5000)
        assert score == 0.0

    def test_403_adds_hard_block_penalty(self):
        score = _compute_risk_score(403, {}, {"waf": 0, "captcha": 0, "botdet": 0, "status": 1}, 5000)
        assert score == pytest.approx(0.30)

    def test_cloudflare_waf_adds_score(self):
        vendors = {"cloudflare": ["cf-ray"]}
        score = _compute_risk_score(200, vendors, {"waf": 1, "captcha": 0, "botdet": 0, "status": 0}, 5000)
        assert score == pytest.approx(0.20)

    def test_captcha_marker_adds_score(self):
        score = _compute_risk_score(200, {}, {"waf": 0, "captcha": 1, "botdet": 0, "status": 0}, 5000)
        assert score == pytest.approx(0.25)

    def test_small_response_size_adds_score(self):
        score = _compute_risk_score(200, {}, {"waf": 0, "captcha": 0, "botdet": 0, "status": 0}, 500)
        assert score == pytest.approx(0.10)

    def test_multiple_vendors_capped_at_1(self):
        vendors = {
            "cloudflare": ["cf-ray"],
            "akamai": ["_abck"],
            "perimeterx": ["_px3"],
            "datadome": ["datadome"],
            "imperva": ["_incap_ses"],
        }
        markers = {"waf": 5, "captcha": 1, "botdet": 1, "status": 1}
        score = _compute_risk_score(403, vendors, markers, 500)
        assert score == 1.0


class TestRiskMiddleware:
    def setup_method(self):
        self.middleware = RiskMiddleware(risk_threshold_warn=0.5, risk_threshold_block=0.8)

    def test_clean_response_zero_risk_score(self):
        request = _make_request()
        response = _make_response(200)
        spider = _make_spider()

        with patch.object(self.middleware, "_persist"):
            result = self.middleware.process_response(request, response, spider)

        assert result is response
        assert request.meta["risk_score"] == 0.0
        assert request.meta["block_vendor"] is None

    def test_cloudflare_headers_detected(self):
        request = _make_request()
        response = _make_response(200, headers={"cf-ray": "12345-LHR"})
        spider = _make_spider()

        with patch.object(self.middleware, "_persist"):
            self.middleware.process_response(request, response, spider)

        assert request.meta["risk_score"] > 0
        assert request.meta["block_vendor"] == "cloudflare"

    def test_403_raises_risk_score(self):
        request = _make_request()
        response = _make_response(403)
        spider = _make_spider()

        with patch.object(self.middleware, "_persist"):
            self.middleware.process_response(request, response, spider)

        assert request.meta["risk_score"] >= 0.30

    def test_captcha_body_adds_risk(self):
        request = _make_request()
        body = b"<html><div class='g-recaptcha' data-sitekey='xxx'></div></html>"
        response = _make_response(200, body=body)
        spider = _make_spider()

        with patch.object(self.middleware, "_persist"):
            self.middleware.process_response(request, response, spider)

        assert request.meta["risk_score"] >= 0.25

    def test_small_response_size_adds_risk(self):
        request = _make_request()
        body = b"<html>Blocked</html>"  # < 2000 bytes
        response = _make_response(200, body=body)
        spider = _make_spider()

        with patch.object(self.middleware, "_persist"):
            self.middleware.process_response(request, response, spider)

        assert request.meta["risk_score"] >= 0.10

    def test_multiple_vendors_score_capped(self):
        headers = {
            "cf-ray": "abc",
            "x-datadome": "protected",
        }
        body = b"<html>" + b"_incap_ses" + b"perimeterx" + b"g-recaptcha" + b"fpjs" + b"</html>"
        request = _make_request()
        response = _make_response(403, headers=headers, body=body)
        spider = _make_spider()

        with patch.object(self.middleware, "_persist"):
            self.middleware.process_response(request, response, spider)

        assert request.meta["risk_score"] <= 1.0

    def test_job_id_propagated_to_persist(self):
        """job_id on spider propagates to _persist — covers the S2.5 fix."""
        request = _make_request()
        response = _make_response(200)
        spider = _make_spider()
        spider.job_id = "deadbeef01"

        captured = {}

        def _fake_persist(**kwargs):
            captured.update(kwargs)

        with patch.object(self.middleware, "_persist", side_effect=_fake_persist):
            self.middleware.process_response(request, response, spider)

        assert captured.get("job_id") == "deadbeef01"

    def test_job_id_none_when_spider_has_no_attribute(self):
        request = _make_request()
        response = _make_response(200)
        spider = MagicMock(spec=[])  # no job_id attribute
        spider.url = "https://example.com/"
        spider.crawler = MagicMock()
        spider.crawler.stats.get_value.return_value = None

        captured = {}

        def _fake_persist(**kwargs):
            captured.update(kwargs)

        with patch.object(self.middleware, "_persist", side_effect=_fake_persist):
            self.middleware.process_response(request, response, spider)

        assert captured.get("job_id") is None

    def test_from_crawler_reads_settings(self):
        crawler = MagicMock()
        crawler.settings.getfloat.side_effect = lambda key, default: (
            0.6 if key == "RISK_THRESHOLD_WARN" else 0.9
        )
        mw = RiskMiddleware.from_crawler(crawler)
        assert mw.threshold_warn == pytest.approx(0.6)
        assert mw.threshold_block == pytest.approx(0.9)
