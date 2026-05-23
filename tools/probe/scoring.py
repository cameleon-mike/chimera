"""Scoring logic: compute risk_score from probe features and map to recommendation."""
from __future__ import annotations

from tools.common.block_indicators import BLOCK_INDICATORS  # noqa: F401 — shared constants


def compute_risk_score(features: dict) -> tuple[float, dict]:
    """Return (risk_score clamped 0..1, recommendation dict).

    Args:
        features: dict with keys:
            vendors_detected: list[str]
            captcha_detected: bool
            botdet_detected: bool
            hsts_strict: bool          # maxAge > 31536000
            csp_strict: bool           # contains "default-src 'self'"
            x_frame_deny: bool
            http_status: int
    """
    score = 0.0

    vendors = features.get("vendors_detected") or []
    vendor_contribution = min(len(vendors) * 0.15, 0.60)
    score += vendor_contribution

    if features.get("captcha_detected"):
        score += 0.20

    if features.get("botdet_detected"):
        score += 0.15

    if features.get("hsts_strict"):
        score += 0.10

    if features.get("csp_strict"):
        score += 0.10

    if features.get("x_frame_deny"):
        score += 0.05

    if features.get("http_status") in {403, 429, 503}:
        score += 0.05

    score = min(score, 1.0)

    from network.fingerprints.loader import FingerprintLoader as _FPLoader
    try:
        _fp = _FPLoader().pick_coherent(geo_id=None)["profile_id"]
    except Exception:
        _fp = "chrome127-win"

    if score < 0.2:
        recommendation = {
            "tool": "scrapy",
            "proxy_tier": "datacenter",
            "fingerprint": _fp,
        }
    elif score < 0.5:
        recommendation = {
            "tool": "scrapy",
            "proxy_tier": "residential",
            "fingerprint": _fp,
        }
    elif score < 0.8:
        recommendation = {
            "tool": "crawl4ai",
            "proxy_tier": "residential",
            "fingerprint": _fp,
        }
    else:
        recommendation = {
            "tool": "screenshot",
            "proxy_tier": "residential",
            "fingerprint": _fp,
        }

    return score, recommendation
