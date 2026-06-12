#!/usr/bin/env python3
"""Camoufox Runner — Chimera stealth tool.

Headless Firefox (Camoufox) that fetches a URL and returns HTML + markdown.
Mirrors the JSON-stdin → JSON-stdout CLI of the other Chimera runners.

Input  (stdin) : JSON payload
Output (stdout): JSON result
Exit codes:
  0  success (includes graceful {"error": ...} payloads — fetch never crashes)
  2  validation error (missing url)

Payload fields:
  url           str   required  Target URL
  wait_ms       int   optional  Delay after load before HTML capture (default 3000)
  proxy_config  dict  optional  {"country": "BE"} → Bright Data residential proxy

Anti-bot:
  - Camoufox Windows fingerprint + geoip-aligned locale/timezone
  - Virtual display (Xvfb) when available, else true-headless
  - humanize cursor movement + randomized human delay before navigation
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timezone
from shutil import which

from bs4 import BeautifulSoup
from camoufox.sync_api import Camoufox

# Tags whose text content is noise for downstream extraction.
_STRIP_TAGS = ("script", "style", "noscript", "nav", "footer", "header",
               "aside", "form", "svg")
# Class/id substrings that usually mark ads / chrome.
_STRIP_HINTS = ("advert", "ads-", "-ads", "ad-banner", "cookie", "consent",
                "newsletter", "popup")


class CamoufoxRunner:
    """Fetch a URL with a stealth Firefox and return HTML + markdown."""

    def __init__(self, proxy_config: dict | None = None):
        self.proxy_config = proxy_config

    def fetch(self, url: str, wait_ms: int = 3000) -> dict:
        """Fetch ``url`` and return a result dict. Never raises."""
        started = time.time()
        try:
            proxy = self._build_proxy(self.proxy_config)

            launch_kwargs: dict = dict(
                headless="virtual" if self._xvfb_available() else True,
                geoip=True,
                os="windows",
                humanize=True,
            )
            if proxy:
                launch_kwargs["proxy"] = proxy

            with Camoufox(**launch_kwargs) as browser:
                # ignore_https_errors so proxy-tunnelled TLS (Bright Data) is
                # not rejected with SEC_ERROR_UNKNOWN_ISSUER.
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()

                # Human delay before navigation (anti-bot).
                time.sleep(random.uniform(0.5, 1.5))

                resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Best-effort settle, then explicit dwell for late JS.
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                if wait_ms:
                    page.wait_for_timeout(wait_ms)

                html = page.content()
                final_url = page.url
                http_status = resp.status if resp is not None else 0
                cookies = page.context.cookies()

            markdown = self._html_to_markdown(html)
            return {
                "url": url,
                "final_url": final_url,
                "http_status": http_status,
                "html": html,
                "html_len": len(html),
                "markdown": markdown,
                "markdown_len": len(markdown),
                "cookies": cookies,
                "duration_ms": int((time.time() - started) * 1000),
                "tool": "camoufox",
            }
        except Exception as exc:
            # Defense-in-depth: never let a proxy password reach stdout via an
            # exception message (Playwright errors can echo connection strings).
            msg = str(exc)
            secret = (self.proxy_config or {}) and self._proxy_password()
            if secret:
                msg = msg.replace(secret, "***")
            return {
                "url": url,
                "error": msg,
                "duration_ms": int((time.time() - started) * 1000),
                "tool": "camoufox",
            }

    def _html_to_markdown(self, html: str) -> str:
        """Strip chrome/ads and return clean text. Never raises."""
        try:
            soup = BeautifulSoup(html or "", "html.parser")
            for tag in soup(list(_STRIP_TAGS)):
                tag.decompose()
            for el in soup.find_all(attrs={"class": True}) + soup.find_all(attrs={"id": True}):
                ident = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
                if any(hint in ident.lower() for hint in _STRIP_HINTS):
                    el.decompose()
            text = soup.get_text(separator="\n")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            return "\n".join(lines)
        except Exception:
            return ""

    def _build_proxy(self, proxy_config: dict | None) -> dict | None:
        """Build a Playwright-compatible Bright Data proxy dict, or None.

        Credentials come from get_settings() (never read scraper.env directly).
        Playwright/Firefox require username/password as separate fields, not
        inline in the server URL.
        """
        if not proxy_config:
            return None
        from bridge.config import get_settings

        s = get_settings()
        if not s.brightdata_username or not s.brightdata_password:
            return None

        username = s.brightdata_username
        country = proxy_config.get("country")
        if country:
            username = f"{username}-country-{str(country).lower()}"

        return {
            "server": f"http://{s.brightdata_host}:{s.brightdata_port}",
            "username": username,
            "password": s.brightdata_password,
        }

    def _proxy_password(self) -> str:
        """Return the configured Bright Data password (for scrubbing), or ''."""
        try:
            from bridge.config import get_settings

            return get_settings().brightdata_password or ""
        except Exception:
            return ""

    def _xvfb_available(self) -> bool:
        """True if Xvfb is installed (enables Camoufox 'virtual' display)."""
        return which("Xvfb") is not None


def main() -> None:
    payload = json.load(sys.stdin)
    url = payload.get("url")
    if not url:
        print(json.dumps({"error": "url_required"}), file=sys.stderr)
        sys.exit(2)
    runner = CamoufoxRunner(proxy_config=payload.get("proxy_config"))
    result = runner.fetch(url, wait_ms=payload.get("wait_ms", 3000))
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
