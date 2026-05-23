"""Tests for scoring.compute_risk_score — 5 scenarios."""
from __future__ import annotations
import pytest
from tools.probe.scoring import compute_risk_score


def _base_features(**kwargs):
    defaults = {
        "vendors_detected": [],
        "captcha_detected": False,
        "botdet_detected": False,
        "hsts_strict": False,
        "csp_strict": False,
        "x_frame_deny": False,
        "http_status": 200,
    }
    defaults.update(kwargs)
    return defaults


def test_clean_site_low_score():
    score, rec = compute_risk_score(_base_features())
    assert score == 0.0
    assert rec["tool"] == "scrapy"
    assert rec["proxy_tier"] == "datacenter"


def test_single_waf_vendor():
    score, rec = compute_risk_score(_base_features(vendors_detected=["cloudflare"]))
    assert score == pytest.approx(0.15)
    # 0.15 < 0.2 → datacenter (per spec ok_max=0.2)
    assert rec["proxy_tier"] == "datacenter"


def test_captcha_plus_waf():
    score, rec = compute_risk_score(
        _base_features(vendors_detected=["cloudflare", "akamai"], captcha_detected=True)
    )
    assert score == pytest.approx(0.30 + 0.20)
    assert rec["tool"] in {"crawl4ai", "scrapy"}


def test_heavy_protection_capped_at_1():
    score, rec = compute_risk_score(_base_features(
        vendors_detected=["cloudflare", "akamai", "perimeterx", "datadome", "imperva"],
        captcha_detected=True,
        botdet_detected=True,
        hsts_strict=True,
        csp_strict=True,
        x_frame_deny=True,
        http_status=403,
    ))
    assert score == 1.0
    assert rec["tool"] == "screenshot"
    assert rec["proxy_tier"] == "residential"


def test_403_status_adds_points():
    score, rec = compute_risk_score(_base_features(http_status=403))
    assert score == pytest.approx(0.05)


def test_fallback_fingerprint_on_loader_error(monkeypatch):
    """TD-15: when FingerprintLoader raises, recommendation fingerprint = 'chrome127-win'."""
    import network.fingerprints.loader as fp_module

    class _BrokenLoader:
        def __init__(self, *a, **kw):
            raise RuntimeError("simulated FingerprintLoader failure")

    monkeypatch.setattr(fp_module, "FingerprintLoader", _BrokenLoader)
    score, rec = compute_risk_score(_base_features())
    assert rec["fingerprint"] == "chrome127-win"
