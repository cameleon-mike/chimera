#!/usr/bin/env python3
"""Screenshot Runner — Chimera tool.

Input  (stdin) : JSON payload
Output (stdout): JSON result
Exit codes: 0=success, 2=validation error, 3=runtime error

Payload fields:
  url            str   required  Target URL
  job_id         str   optional  Generated if absent
  profile_id     str   optional  Browser profile dir under storage/cookies (default: "default")
  session_id     str   optional  Used for canvas seed derivation; defaults to profile_id
  headless       bool  optional  default true
  wait_until     str   optional  networkidle|domcontentloaded (default: networkidle)
  wait_ms        int   optional  Extra wait after page load in ms (default: 0)
  full_page      bool  optional  Full-page screenshot (default: true)
  locale         str   optional  Browser locale (default: fr-FR)
  tz             str   optional  Timezone (default: Europe/Paris)
  ua             str   optional  User-Agent override
  proxy_country  str   optional  ISO 2-letter code (BE/FR/DE/GB/NL). No proxy if omitted.
  proxy_tier     str   optional  residential|datacenter (default: residential)
  timeout        int   optional  Navigation timeout ms (default: 30000)
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from network.proxy_pool.brightdata import get_proxy_for_profile
from tools.screenshot_runner.stealth.loader import load_stealth_script, session_seed_from_id

_VIEWPORTS = [(1920, 1080), (1536, 864), (1440, 900), (1366, 768)]


async def run(payload: dict) -> dict:
    from bridge.config import get_settings
    s = get_settings()
    shots_dir = s.screenshots_dir
    profiles_dir = s.cookies_dir

    job_id       = payload.get("job_id") or uuid.uuid4().hex[:16]
    url          = payload.get("url", "")
    profile_id   = payload.get("profile_id", "default")
    session_id   = payload.get("session_id") or profile_id
    headless     = payload.get("headless", True)
    wait_until   = payload.get("wait_until", "networkidle")
    wait_ms      = payload.get("wait_ms", 0)
    full_page    = payload.get("full_page", True)
    locale       = payload.get("locale", "fr-FR")
    tz           = payload.get("tz", "Europe/Paris")
    proxy_country = payload.get("proxy_country")
    proxy_tier   = payload.get("proxy_tier", "residential")
    ua           = payload.get("ua")
    timeout      = payload.get("timeout", 30000)

    shots_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / profile_id
    profile_path.mkdir(parents=True, exist_ok=True)

    vp_w, vp_h = random.choice(_VIEWPORTS)

    proxy = None
    if proxy_country:
        proxy = get_proxy_for_profile(proxy_country, proxy_tier)

    seed = session_seed_from_id(session_id)
    stealth_script = load_stealth_script(session_seed=seed)

    async with async_playwright() as pw:
        launch_kwargs = {
            "user_data_dir": str(profile_path),
            "headless": headless,
            "viewport": {"width": vp_w, "height": vp_h},
            "locale": locale,
            "timezone_id": tz,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        if proxy is not None:
            launch_kwargs["proxy"] = proxy
        if ua is not None:
            launch_kwargs["user_agent"] = ua

        ctx = await pw.chromium.launch_persistent_context(**launch_kwargs)

        # Stealth BEFORE any page load
        await ctx.add_init_script(stealth_script)

        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception as exc:
            if "networkidle" in str(exc):
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            else:
                raise

        if wait_ms:
            await page.wait_for_timeout(wait_ms)

        for _ in range(random.randint(2, 5)):
            await page.mouse.wheel(0, random.randint(200, 600))
            await page.wait_for_timeout(random.randint(300, 800))

        png_path = shots_dir / f"{job_id}.png"
        await page.screenshot(path=str(png_path), full_page=full_page)

        final_url = page.url
        title     = await page.title()
        html_len  = len(await page.content())
        cookies   = await ctx.cookies()

        await ctx.close()

    return {
        "job_id":             job_id,
        "tool":               "screenshot",
        "url":                url,
        "final_url":          final_url,
        "screenshot_path":    str(png_path),
        "screenshot_size_kb": round(png_path.stat().st_size / 1024, 1),
        "viewport":           {"w": vp_w, "h": vp_h},
        "cookies_count":      len(cookies),
        "title":              title,
        "html_len":           html_len,
        "profile_id":         profile_id,
        "proxy_used":         proxy is not None,
        "proxy_country":      proxy_country,
        "stealth_seed":       seed,
        "ts":                 datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    payload = json.load(sys.stdin)
    if not payload.get("url"):
        print(json.dumps({"error": "missing url"}), file=sys.stderr)
        sys.exit(2)
    result = asyncio.run(run(payload))
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
