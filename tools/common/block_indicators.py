"""Shared WAF/bot-detection block indicators.

Single source of truth. Imported by tools.probe.scoring and
tools.scrapy_runner.project.middlewares.risk_signals.
"""
from __future__ import annotations

BLOCK_INDICATORS: dict[str, list[str]] = {
    "cloudflare":  ["__cf_chl_", "cf-mitigated", "just a moment",
                    "cf-ray", "cloudflare ray id"],
    "akamai":      ["_abck", "akamai-bot", "ak-bm-pixel", "akamai-edge"],
    "perimeterx":  ["px-captcha", "_px3", "_pxhd", "perimeterx"],
    "datadome":    ["datadome", "dd-protected", "x-datadome",
                    "geo.captcha-delivery.com"],
    "imperva":     ["_incap_ses", "incap_ses_", "visid_incap", "imperva"],
    "captcha":     ["g-recaptcha", "hcaptcha", "turnstile",
                    "captcha-form", "captcha challenge"],
    "botdet":      ["fpjs", "fingerprintjs", "fingerprint2",
                    "botdetect", "challenge-platform"],
}

WAF_VENDORS = {"cloudflare", "akamai", "perimeterx", "datadome", "imperva"}
CHALLENGE_KEYS = {"captcha", "botdet"}
