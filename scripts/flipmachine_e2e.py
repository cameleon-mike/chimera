#!/usr/bin/env python3
"""FLIPMACHINE E2E validation — 3 produits test MVP."""

import os
import sys
from datetime import date

import requests

PRODUITS_TEST = [
    {"query": "wacom cintiq 16",          "marketplace": "EBAY_FR"},
    {"query": "gopro hero",               "marketplace": "EBAY_FR"},
    {"query": "steelseries apex pro tkl", "marketplace": "EBAY_FR"},
]


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


def _get_config() -> tuple[str, str]:
    """Return (base_url, auth_token), reading token from env or scraper.env."""
    base_url = os.environ.get("BRIDGE_BASE_URL", "http://127.0.0.1:8080")
    token = os.environ.get("BRIDGE_AUTH_TOKEN", "")
    if not token:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(script_dir, "..", "scraper.env")
        env_data = _read_scraper_env(env_path)
        token = env_data.get("BRIDGE_AUTH_TOKEN", "")
    return base_url, token


def main() -> dict:
    base_url, token = _get_config()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    results: dict = {}

    for product in PRODUITS_TEST:
        query = product["query"]
        marketplace = product["marketplace"]
        result = {
            "total_items": 0,
            "sources": {},
            "epid_coverage": 0.0,
            "epids_found": [],
            "median_price": None,
            "currency": None,
            "avg_sell_days": None,
            "success": False,
        }

        crit_no_error = True
        try:
            url = f"{base_url}/aggregate/search"
            params = {"q": query, "marketplace": marketplace, "ingest": "true"}
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code in (401, 500):
                crit_no_error = False
                result["success"] = False
                results[query] = result
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            crit_no_error = False
            result["success"] = False
            results[query] = result
            print(f"  ERROR [{query}]: {exc}")
            continue

        total_items = data.get("total_items", 0)
        sources = data.get("sources", {})
        items = data.get("items", [])

        result["total_items"] = total_items
        result["sources"] = sources

        # epid coverage
        items_with_epid = [i for i in items if i.get("epid")]
        epid_coverage = (len(items_with_epid) / total_items * 100) if total_items > 0 else 0.0
        result["epid_coverage"] = epid_coverage

        # unique epids (preserve order)
        seen: set = set()
        unique_epids: list = []
        for i in items:
            epid = i.get("epid")
            if epid and epid not in seen:
                seen.add(epid)
                unique_epids.append(epid)
        result["epids_found"] = unique_epids

        # epid stats for first epid
        if unique_epids:
            first_epid = unique_epids[0]
            try:
                stats_url = f"{base_url}/epid/stats/{first_epid}"
                stats_resp = requests.get(stats_url, headers=headers, timeout=30)
                if stats_resp.status_code not in (401, 500):
                    stats_resp.raise_for_status()
                    stats_data = stats_resp.json()
                    result["median_price"] = stats_data.get("median_price")
                    result["currency"] = stats_data.get("currency")
                    result["avg_sell_days"] = stats_data.get("avg_sell_days")
            except Exception as exc:
                print(f"  WARN [{query}] epid stats error: {exc}")

        # success criteria
        crit_items = total_items > 0
        crit_epids = len(unique_epids) >= 1 or epid_coverage >= 5.0
        crit_price = (result["median_price"] is not None) if unique_epids else True
        result["success"] = crit_no_error and crit_items and crit_epids and crit_price

        results[query] = result

    # --- Print output ---
    today = date.today().isoformat()
    print("=" * 30)
    print(f"FLIPMACHINE E2E — {today}")
    print()

    passed = 0
    for product in PRODUITS_TEST:
        query = product["query"]
        r = results.get(query, {})
        sources = r.get("sources", {})
        sources_str = ", ".join(f"{k}={v}" for k, v in sources.items())
        epid_cov = r.get("epid_coverage", 0.0)
        epids = r.get("epids_found", [])
        median = r.get("median_price")
        currency = r.get("currency", "")
        avg_days = r.get("avg_sell_days")

        median_str = f"{median:.1f} {currency}" if median is not None else "null"
        avg_str = f"{avg_days}" if avg_days is not None else "null (insuffisant — attendu)"

        print(f"  [{query}]")
        print(f"    total_items    : {r.get('total_items', 0)}")
        print(f"    sources        : {sources_str}")
        print(f"    epid_coverage  : {epid_cov:.1f}%")
        print(f"    epids_found    : {epids}")
        print(f"    median_price   : {median_str}")
        print(f"    avg_sell_days  : {avg_str}")
        print()

        if r.get("success"):
            passed += 1

    total = len(PRODUITS_TEST)
    print("=" * 30)
    status = "✓" if passed == total else "✗"
    print(f"RÉSULTAT : {passed}/{total} produits validés {status}")

    return results


if __name__ == "__main__":
    results = main()
    all_passed = all(r.get("success", False) for r in results.values())
    sys.exit(0 if all_passed else 1)
