"""Tests for _build_escalation logic in run_scrapy."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tools.scrapy_runner.run_scrapy import _build_escalation


def _rows(scores: list[float], vendors: list[str] | None = None) -> list[tuple[float, str]]:
    """Build mock rows as (risk_score, vendors_json)."""
    vj = json.dumps(vendors or [])
    return [(s, vj) for s in scores]


def test_no_data_returns_not_needed():
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=[]):
        result = _build_escalation("job1", ["https://example.com"])
    assert result["needed"] is False
    assert result["reason"] == "no_risk_data"
    assert result["suggested_tool"] is None
    assert result["vendors_detected"] == []


def test_high_risk_triggers_escalation():
    rows = _rows([0.6, 0.7, 0.8])  # all >= 0.5, so high_risk_count/total = 100% >= 50%
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job2", ["https://example.com"])
    assert result["needed"] is True


def test_max_risk_1_suggests_screenshot():
    rows = _rows([1.0])
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job3", ["https://example.com"])
    assert result["needed"] is True
    assert result["suggested_tool"] == "screenshot"


def test_avg_risk_0_8_suggests_screenshot():
    rows = _rows([0.8, 0.8])
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job4", ["https://example.com"])
    assert result["suggested_tool"] == "screenshot"


def test_avg_risk_0_6_suggests_crawl4ai():
    rows = _rows([0.6, 0.6])
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job5", ["https://example.com"])
    assert result["suggested_tool"] == "crawl4ai"


def test_low_risk_no_escalation():
    rows = _rows([0.1, 0.1, 0.1])
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job6", ["https://example.com"])
    assert result["needed"] is False
    assert result["suggested_tool"] is None


def test_vendors_detected_aggregated():
    rows = [
        (0.7, json.dumps(["cloudflare"])),
        (0.6, json.dumps(["akamai", "cloudflare"])),
    ]
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job7", ["https://example.com"])
    assert "cloudflare" in result["vendors_detected"]
    assert "akamai" in result["vendors_detected"]
    assert result["vendors_detected"] == sorted(result["vendors_detected"])


def test_trigger_threshold_always_0_5():
    rows = _rows([0.3])
    with patch("tools.scrapy_runner.run_scrapy._get_job_scores", return_value=rows):
        result = _build_escalation("job8", ["https://example.com"])
    assert result["trigger_threshold"] == 0.5
