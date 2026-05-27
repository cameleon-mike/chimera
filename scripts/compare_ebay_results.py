#!/usr/bin/env python3
"""Compare eBay results from Chimera bridge vs secondpulse_v9.py."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


def _load_token() -> str:
    token = os.environ.get("BRIDGE_AUTH_TOKEN", "")
    if not token:
        env_path = Path(__file__).parent.parent / "scraper.env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("BRIDGE_AUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    return token


def _chimera_search(q: str, marketplace: str, base_url: str, token: str) -> list[dict]:
    resp = requests.get(
        f"{base_url}/ebay/search",
        params={"q": q, "marketplace": marketplace},
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def _v9_search(q: str, marketplace: str) -> list[dict]:
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import importlib
        v9 = importlib.import_module("secondpulse_v9")
        fn = getattr(v9, "search_ebay", None) or getattr(v9, "search", None)
        if fn:
            return fn(q=q, marketplace_id=marketplace) or []
        print("Warning: secondpulse_v9 found but no search function", file=sys.stderr)
    except ImportError:
        print("Warning: secondpulse_v9.py not importable — skipping v9", file=sys.stderr)
    return []


def _compare(chimera: list[dict], v9: list[dict]) -> dict:
    def epids(items):
        return {i.get("epid") for i in items if i.get("epid")}

    c_epids, v_epids = epids(chimera), epids(v9)

    def avg_price(items):
        prices = []
        for i in items:
            p = i.get("price")
            if isinstance(p, dict):
                v = p.get("value")
            else:
                v = p
            if v is not None:
                try:
                    prices.append(float(v))
                except (TypeError, ValueError):
                    pass
        return round(sum(prices) / len(prices), 2) if prices else None

    return {
        "chimera_count": len(chimera),
        "v9_count": len(v9),
        "chimera_epid_coverage_pct": round(len(c_epids) / max(len(chimera), 1) * 100, 1),
        "v9_epid_coverage_pct": round(len(v_epids) / max(len(v9), 1) * 100, 1),
        "epid_intersection": len(c_epids & v_epids),
        "epid_only_chimera": len(c_epids - v_epids),
        "epid_only_v9": len(v_epids - c_epids),
        "chimera_avg_price": avg_price(chimera),
        "v9_avg_price": avg_price(v9),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Compare eBay results: Chimera vs secondpulse_v9")
    p.add_argument("--query", required=True, help="Search query")
    p.add_argument("--marketplace", default="EBAY_FR")
    p.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = p.parse_args()

    token = _load_token()
    if not token:
        print("Error: BRIDGE_AUTH_TOKEN not found", file=sys.stderr)
        return 1

    print(f"[chimera] searching: {args.query}", file=sys.stderr)
    chimera_items = _chimera_search(args.query, args.marketplace, args.base_url, token)

    print(f"[v9] searching: {args.query}", file=sys.stderr)
    v9_items = _v9_search(args.query, args.marketplace)

    report = {
        "query": args.query,
        "marketplace": args.marketplace,
        "ts": datetime.now(timezone.utc).isoformat(),
        "comparison": _compare(chimera_items, v9_items),
        "chimera_sample": chimera_items[:3],
        "v9_sample": v9_items[:3],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
