#!/usr/bin/env python3
"""Live validation of the watchcount vision pipeline."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

# Load TOKEN from scraper.env
ENV_PATH = Path(__file__).parent.parent / "scraper.env"

token = None
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        m = re.match(r"^BRIDGE_AUTH_TOKEN=(.+)$", line.strip())
        if m:
            token = m.group(1).strip().strip('"').strip("'")
            break

if not token:
    print("ERROR: BRIDGE_AUTH_TOKEN not found in scraper.env")
    sys.exit(1)

BASE_URL = "http://127.0.0.1:8080"
HEADERS = {"Authorization": f"Bearer {token}"}

# Step 1: GET /watchcount/search
resp = requests.get(
    f"{BASE_URL}/watchcount/search",
    params={"q": "wacom cintiq 16"},
    headers=HEADERS,
    timeout=120,
)
resp.raise_for_status()
data = resp.json()

tool_used = data.get("tool_used", "unknown")
total_items = data.get("total_items", 0)
items = data.get("items", [])

first_end_date = "no items"
if items:
    first_end_date = items[0].get("end_date") or "no end_date"

print(f"tool_used: {tool_used}")
print(f"total_items: {total_items}")
print(f"first end_date: {first_end_date}")

# Step 2: If items found with end_date, ingest and get stats
items_with_dates = [i for i in items if i.get("end_date")]
if items_with_dates:
    ingest_payload = {
        "items": [
            {
                "title": i.get("title"),
                "end_date": i.get("end_date"),
                "price": i.get("price"),
                "watch_count": i.get("watch_count"),
                "source": "watchcount",
            }
            for i in items_with_dates
        ],
        "source": "watchcount",
    }
    ingest_resp = requests.post(
        f"{BASE_URL}/epid/ingest",
        json=ingest_payload,
        headers=HEADERS,
        timeout=30,
    )
    print(f"ingest status: {ingest_resp.status_code}")

    # Find first ePID
    epid = None
    for i in items_with_dates:
        if i.get("epid"):
            epid = i["epid"]
            break

    if epid:
        stats_resp = requests.get(
            f"{BASE_URL}/epid/stats/{epid}",
            headers=HEADERS,
            timeout=30,
        )
        if stats_resp.status_code == 200:
            stats = stats_resp.json()
            print(f"avg_sell_days: {stats.get('avg_sell_days')}")
        else:
            print(f"stats fetch failed: {stats_resp.status_code}")
    else:
        print("no epid found in items")
