"""Bright Data proxy URL builder.

Bright Data supports country targeting via the username suffix:
  brd-customer-XXXXX-zone-XXXXX-country-be

Credentials are read from Settings (BRIGHTDATA_* env vars in scraper.env).
Never log the returned URL — it contains the password.
"""
from __future__ import annotations

from bridge.config import get_settings


def build_proxy_url(country: str | None = None, tier: str = "residential") -> str | None:
    """Build a Bright Data proxy URL for a given country and tier.

    Args:
        country: ISO 2-letter code (BE, FR, DE, GB, NL, US…). None = no pinning.
        tier: informational ("residential" or "datacenter") — affects port selection
              in the future; currently always uses brightdata_port from settings.

    Returns:
        Full proxy URL or None if credentials are not configured.
    """
    s = get_settings()
    if not s.brightdata_username or not s.brightdata_password:
        return None

    username = s.brightdata_username
    if country:
        username = f"{username}-country-{country.lower()}"

    return f"http://{username}:{s.brightdata_password}@{s.brightdata_host}:{s.brightdata_port}"


def get_proxy_for_profile(proxy_country: str, tier: str = "residential") -> dict | None:
    """Return a Playwright-compatible proxy dict for a profile.

    Returns None if credentials are not configured (so callers can pass proxy=None
    to Playwright and fall back to a direct connection).
    """
    url = build_proxy_url(country=proxy_country, tier=tier)
    if not url:
        return None
    return {"server": url}
