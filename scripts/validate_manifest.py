#!/usr/bin/env python3
"""
Sanity-check tool_manifest.json.

This is the SINGLE SOURCE OF TRUTH for cameleon. Future steps will derive
Pydantic schemas, the /capabilities endpoint, and OpenAPI descriptions
from this file — so the structural contract enforced here matters.

For Step 1.1 the check is intentionally light. Step 1.2 will replace this
with a proper JSON Schema validation.
"""

import json
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL = {
    "manifest_version",
    "name",
    "discovery",
    "auth",
    "tools",
    "proxy_tiers",
    "risk_thresholds",
    "escalation_policy",
    "endpoints",
}

REQUIRED_TOOLS = {"probe", "scrapy", "firecrawl", "crawl4ai", "screenshot", "bypass_waf"}


def main() -> int:
    path = Path(__file__).resolve().parent.parent / "tool_manifest.json"
    if not path.exists():
        print(f"FAIL: {path} not found")
        return 1

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"FAIL: invalid JSON — {e}")
        return 1

    missing = REQUIRED_TOP_LEVEL - data.keys()
    if missing:
        print(f"FAIL: missing top-level keys: {sorted(missing)}")
        return 1

    tools = set(data.get("tools", {}).keys())
    missing_tools = REQUIRED_TOOLS - tools
    if missing_tools:
        print(f"FAIL: missing tools: {sorted(missing_tools)}")
        return 1

    print(f"OK: manifest v{data['manifest_version']} — "
          f"{len(tools)} tools, {len(data['proxy_tiers'])} proxy tiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
