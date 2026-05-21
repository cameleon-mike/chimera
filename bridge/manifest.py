"""Loader for `tool_manifest.json` — the SINGLE SOURCE OF TRUTH for cameleon.

Pydantic schemas, the /capabilities endpoint, and OpenAPI descriptions all
derive from this file at runtime (per Mike's decision: option (2) for S1-S3,
switching to build-time codegen in S6).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "tool_manifest.json"


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def manifest_version() -> str:
    return str(load_manifest()["manifest_version"])


def list_tool_names() -> list[str]:
    """Ordered list of tools declared in the manifest."""
    return list(load_manifest()["tools"].keys())


def get_tool(name: str) -> dict[str, Any]:
    return load_manifest()["tools"][name]


def get_proxy_tiers() -> dict[str, Any]:
    return load_manifest()["proxy_tiers"]


def get_risk_thresholds() -> dict[str, float]:
    return load_manifest()["risk_thresholds"]


def get_escalation_policy() -> dict[str, Any]:
    return load_manifest()["escalation_policy"]
