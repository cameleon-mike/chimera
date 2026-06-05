#!/usr/bin/env python3
"""Thin wrapper — delegates to ScrapingAgent."""
import os
import sys
from pathlib import Path


def _read_env(path):
    result = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return result


def _config():
    env_path = Path(__file__).parent.parent / "scraper.env"
    env = _read_env(env_path)
    token = os.environ.get("BRIDGE_AUTH_TOKEN") or env.get("BRIDGE_AUTH_TOKEN", "")
    base_url = os.environ.get("BRIDGE_BASE_URL", "http://127.0.0.1:8080")
    products_raw = os.environ.get("SCRAPE_PRODUCTS") or env.get("SCRAPE_PRODUCTS", "wacom cintiq 16,gopro hero,steelseries apex pro tkl")
    products = [p.strip() for p in products_raw.split(",") if p.strip()]
    interval_hours = int(os.environ.get("SCRAPE_INTERVAL_HOURS") or env.get("SCRAPE_INTERVAL_HOURS", "6"))
    watchcount_hour = int(os.environ.get("WATCHCOUNT_DAILY_HOUR") or env.get("WATCHCOUNT_DAILY_HOUR", "2"))
    return base_url, token, products, interval_hours, watchcount_hour


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    base_url, token, products, interval_hours, watchcount_hour = _config()
    from tools.scraping_agent.agent import ScrapingAgent
    agent = ScrapingAgent(base_url=base_url, token=token, products=products, interval_hours=interval_hours, watchcount_hour=watchcount_hour)
    if "--once" in sys.argv:
        import json
        report = agent.run_once()
        print(json.dumps(report, indent=2))
    else:
        agent.start_scheduler()
