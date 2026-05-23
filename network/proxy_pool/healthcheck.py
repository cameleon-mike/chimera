"""Standalone proxy healthcheck. Run with:
    .venv/bin/python -m network.proxy_pool.healthcheck
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


def check_proxies(pool_file: Path | None = None) -> dict:
    if pool_file is None:
        pool_file = Path(__file__).parent / "pool.json"
    pool = json.loads(pool_file.read_text(encoding="utf-8"))
    results = {}
    for tier, proxies in pool.get("tiers", {}).items():
        results[tier] = []
        for proxy in proxies:
            url = proxy.get("url", "")
            if proxy.get("_mock"):
                results[tier].append({
                    "url": url,
                    "active": False,
                    "reason": "mock_entry",
                })
                continue
            try:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": url, "https": url})
                )
                resp = opener.open("https://httpbin.org/ip", timeout=10)
                body = json.loads(resp.read())
                results[tier].append({"url": url, "active": True, "ip": body.get("origin")})
            except Exception as exc:
                results[tier].append({"url": url, "active": False, "reason": str(exc)})
    return results


if __name__ == "__main__":
    output = check_proxies()
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
