#!/usr/bin/env python3
"""Periodic scraper — feeds epid_stats continuously."""

# Crontab entry (alternative to running this script in a loop):
# 0 */6 * * * cd /workspaces/chimera && .venv/bin/python3 scripts/scrape_cron.py --once

import os
import sys
import time

import requests


def _read_scraper_env(path: str) -> dict:
    """Parse a scraper.env file (KEY=VALUE lines) and return a dict."""
    result = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    result[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return result


def _get_config() -> dict:
    """Read configuration from environment variables or scraper.env."""
    base_url = os.environ.get("BRIDGE_BASE_URL", "http://127.0.0.1:8080")
    token = os.environ.get("BRIDGE_AUTH_TOKEN", "")
    if not token:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(script_dir, "..", "scraper.env")
        env_data = _read_scraper_env(env_path)
        token = env_data.get("BRIDGE_AUTH_TOKEN", "")

    interval_raw = os.environ.get("SCRAPE_INTERVAL_MINUTES", "360")
    try:
        interval = int(interval_raw)
    except ValueError:
        interval = 360

    products_raw = os.environ.get(
        "SCRAPE_PRODUCTS",
        "wacom cintiq 16,gopro hero,steelseries apex pro tkl",
    )
    products = [p.strip() for p in products_raw.split(",") if p.strip()]

    marketplace = os.environ.get("SCRAPE_MARKETPLACE", "EBAY_FR")

    return {
        "base_url": base_url,
        "token": token,
        "interval": interval,
        "products": products,
        "marketplace": marketplace,
    }


def scrape_once(config: dict | None = None) -> dict:
    """Scrape all products once. Returns {product: {total_items, sources}}."""
    if config is None:
        config = _get_config()

    base_url = config["base_url"]
    token = config["token"]
    products = config["products"]
    marketplace = config["marketplace"]

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    results: dict = {}

    for idx, product in enumerate(products):
        try:
            url = f"{base_url}/aggregate/search"
            params = {"q": product, "marketplace": marketplace, "ingest": "true"}
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            total_items = data.get("total_items", 0)
            sources = data.get("sources", {})
            print(f"scraped {product}: {total_items} items, sources={sources}")
            results[product] = {"total_items": total_items, "sources": sources}
        except Exception as exc:
            print(f"ERROR scraping {product}: {exc}")
            results[product] = {"total_items": 0, "sources": {}}

        # Sleep 30s between products, but not after the last one
        if idx < len(products) - 1:
            time.sleep(30)

    return results


def main() -> None:
    config = _get_config()
    interval = config["interval"]
    products = config["products"]
    once_mode = "--once" in sys.argv

    print(f"Scrape cron started — interval={interval}min, products={len(products)}")

    if once_mode:
        scrape_once(config)
        return

    while True:
        scrape_once(config)
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
