#!/usr/bin/env python3
"""Crawl4AI Runner — Chimera tool.

Input  (stdin) : JSON payload
Output (stdout): JSON result
Exit codes:
  0  success — includes crawl4ai success=False (crawl completed; target returned an error)
  2  validation error (missing/invalid url)
  3  runtime error (unhandled exception; process crashed)

Payload fields:
  url                  str   required  Target URL
  job_id               str   optional  Generated if absent
  schema               dict  optional  JsonCssExtractionStrategy schema — if absent → markdown mode
  css_selector         str   optional  Scope extraction/markdown to a CSS selector on the page
  headless             bool  optional  default true
  proxy                str   optional  http://user:pass@host:port
  locale               str   optional  Browser locale (default: fr-FR)
  tz                   str   optional  Timezone ID (default: Europe/Paris)
  ua                   str   optional  User-Agent override
  page_timeout         int   optional  Navigation timeout ms (default: 30000)
  wait_ms              int   optional  Delay before HTML capture in ms (default: 0)
  simulate_user        bool  optional  Human-like interactions — scroll, mouse (default: true)
  word_count_threshold int   optional  Min words per block kept in markdown (default: 0)
  cache_mode           str   optional  bypass|enabled|disabled|read_only|write_only (default: bypass)
  session_id           str   optional  Sticky fingerprint/proxy session; same id → same UA+proxy
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

_CACHE_MODES: dict[str, CacheMode] = {
    "bypass":     CacheMode.BYPASS,
    "enabled":    CacheMode.ENABLED,
    "disabled":   CacheMode.DISABLED,
    "read_only":  CacheMode.READ_ONLY,
    "write_only": CacheMode.WRITE_ONLY,
}


async def run(payload: dict) -> dict:
    job_id        = payload.get("job_id") or uuid.uuid4().hex[:16]
    url           = payload.get("url", "")
    schema        = payload.get("schema")
    css_selector  = payload.get("css_selector")
    headless      = payload.get("headless", True)
    proxy         = payload.get("proxy")
    locale        = payload.get("locale", "fr-FR")
    tz            = payload.get("tz", "Europe/Paris")
    ua            = payload.get("ua")
    page_timeout  = payload.get("page_timeout", 30000)
    wait_ms       = int(payload.get("wait_ms", 0))
    simulate_user = payload.get("simulate_user", True)
    wct           = payload.get("word_count_threshold", 0)
    cache_mode    = _CACHE_MODES.get(payload.get("cache_mode", "bypass"), CacheMode.BYPASS)
    session_id    = payload.get("session_id")

    browser_kwargs: dict = dict(headless=headless)
    if ua:
        browser_kwargs["user_agent"] = ua
    if proxy:
        browser_kwargs["proxy"] = proxy
    browser_config = BrowserConfig(**browser_kwargs)

    mode = "extract" if schema else "markdown"
    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False) if schema else None

    run_config_kwargs: dict = dict(
        extraction_strategy=extraction_strategy,
        css_selector=css_selector,
        word_count_threshold=wct,
        cache_mode=cache_mode,
        page_timeout=page_timeout,
        delay_before_return_html=wait_ms / 1000.0 if wait_ms else 0.0,
        simulate_user=simulate_user,
        locale=locale,
        timezone_id=tz,
    )
    if session_id:
        run_config_kwargs["session_id"] = session_id
    run_config = CrawlerRunConfig(**run_config_kwargs)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    final_url   = result.redirected_url or url
    http_status = result.status_code or 0
    html_len    = len(result.html or "")
    title       = (result.metadata or {}).get("title", "")

    out: dict = {
        "job_id":      job_id,
        "tool":        "crawl4ai",
        "url":         url,
        "final_url":   final_url,
        "http_status": http_status,
        "success":     result.success,
        "mode":        mode,
        "proxy":       proxy,
        "html_len":    html_len,
        "title":       title,
        "ts":          datetime.now(timezone.utc).isoformat(),
    }

    if not result.success:
        out["error"] = result.error_message or "crawl4ai returned success=False"
        return out

    if mode == "extract":
        try:
            extracted = json.loads(result.extracted_content or "[]")
        except (json.JSONDecodeError, TypeError):
            extracted = []
        out["extracted"]    = extracted
        out["items_count"]  = len(extracted) if isinstance(extracted, list) else 1
    else:
        md_text = str(result.markdown) if result.markdown else ""
        out["markdown"]     = md_text
        out["markdown_len"] = len(md_text)

    return out


def main() -> None:
    payload = json.load(sys.stdin)
    if not payload.get("url"):
        print(json.dumps({"error": "missing url"}), file=sys.stderr)
        sys.exit(2)
    try:
        result = asyncio.run(run(payload))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(3)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
