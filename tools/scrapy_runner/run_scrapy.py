"""Standalone CLI for the Scrapy runner — JSON in, JSON out.

Usage:
    python -m tools.scrapy_runner.run_scrapy < input.json
    # or
    python -m tools.scrapy_runner.run_scrapy --input-file input.json

Input JSON (matches the bridge's RunToolRequest.config payload):
{
    "tool":  "scrapy",                  # always "scrapy" here
    "url":   "https://..." | ["..."],   # one or many
    "config": {
        "spider":         "api_json" | "adaptive",   # default: "api_json"
        "selectors":      {field: css, ...},          # adaptive only
        "item_selector":  "css",                       # adaptive optional
        "headers":        {name: value, ...},          # added to every request
        "settings":       {"DOWNLOAD_DELAY": 0.5, ...},# scrapy overrides
        "respect_robots": true,                         # default true
        "proxy":          "http://user:pass@host:port", # informational
        "session_id":     "sess_xyz"                    # sticky UA+proxy via SessionManager (Step 2.4)
    },
    "job_id": "<16-hex>"                # optional; generated if absent
}

Output JSON (written to stdout AND to storage/results/{job_id}.json):
{
    "tool":         "scrapy",
    "url":          <input url(s)>,
    "http_status":  <last observed status, int>,
    "proxy":        <config.proxy or null>,
    "risk_score":   <float; placeholder 0.10 until S2 risk middleware>,
    "items":        [<spider yields>],
    "_meta": {
        "spider": "...",
        "job_id": "...",
        "started_at": "...",
        "finished_at": "...",
        "duration_ms": <int>,
        "item_count": <int>
    }
}

Exit codes:
    0 = crawl ran (even if zero items); JSON written.
    2 = invalid input (bad JSON, missing url, unknown spider).
    3 = runtime crash (Twisted reactor / Scrapy internals).
"""

from __future__ import annotations

import argparse

# Set up the Twisted asyncio reactor BEFORE importing scrapy.crawler — Scrapy
# pins the reactor on first import and we want the asyncio one.
import asyncio  # noqa: F401 — imported to ensure event loop exists before Scrapy
import json
import logging
import secrets
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import scrapy  # noqa: F401 — side-effect: registers reactor preference
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# Bridge settings give us the absolute results_dir and tools_log_path.
from bridge.config import get_settings
from tools.scrapy_runner.project.spiders.adaptive import AdaptiveSpider
from tools.scrapy_runner.project.spiders.api_json import ApiJsonSpider
from tools.scrapy_runner.project.spiders.ebay_browse import EbayBrowseSpider
from tools.scrapy_runner.project.spiders.vinted_2ememain import DeuxememainSpider
from tools.scrapy_runner.project.spiders.vinted_spider import VintedSpider
from tools.scrapy_runner.project.spiders.watchcount import WatchCountSpider

import re

_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_SPIDERS = {
    "api_json": ApiJsonSpider,
    "adaptive": AdaptiveSpider,
    "ebay_browse": EbayBrowseSpider,
    "watchcount": WatchCountSpider,
    "2ememain": DeuxememainSpider,
    "vinted": VintedSpider,
}

_SCRAPY_SETTINGS_WHITELIST = {
    "DOWNLOAD_DELAY",
    "CONCURRENT_REQUESTS",
    "CONCURRENT_REQUESTS_PER_DOMAIN",
    "AUTOTHROTTLE_TARGET_CONCURRENCY",
    "ROBOTSTXT_OBEY",
    "USER_AGENT",
    "DEFAULT_REQUEST_HEADERS",
    "RETRY_TIMES",
    "DOWNLOAD_TIMEOUT",
    "PROXY_TIER",
    "FINGERPRINTS_DIR",
    "GEO_ID",
    "RISK_THRESHOLD_WARN",
    "RISK_THRESHOLD_BLOCK",
    "SESSION_REDIS_URL",
    "SESSION_TTL",
    "SESSION_ID",
}


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _setup_file_logging() -> logging.Logger:
    """Pipe Python+Scrapy logs to logs/tools.log (JSON line per record).
    stdout stays clean so the final JSON result is the only thing on it."""
    settings = get_settings()
    settings.tools_log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":%(message)r}'
    handler = logging.FileHandler(settings.tools_log_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return logging.getLogger("scrapy_runner")


def _read_input(argv) -> dict[str, Any]:
    p = argparse.ArgumentParser(description="Chimera Scrapy runner — JSON in, JSON out.")
    p.add_argument("--input-file", help="Read JSON from this file instead of stdin.")
    args = p.parse_args(argv)
    raw = Path(args.input_file).read_text(encoding="utf-8") if args.input_file else sys.stdin.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": "invalid_json", "detail": str(e)}), file=sys.stderr)
        sys.exit(2)


def _validate(payload: dict[str, Any]) -> tuple[list[str], str, dict[str, Any], str]:
    url = payload.get("url")
    if isinstance(url, str):
        urls = [url]
    elif isinstance(url, list) and url and all(isinstance(u, str) for u in url):
        urls = url
    else:
        print(json.dumps({"error": "url_required"}), file=sys.stderr)
        sys.exit(2)

    config = payload.get("config") or {}
    spider_name = config.get("spider") or payload.get("spider") or "api_json"
    if spider_name not in _SPIDERS:
        print(json.dumps({"error": "unknown_spider", "spider": spider_name,
                          "available": sorted(_SPIDERS)}), file=sys.stderr)
        sys.exit(2)

    job_id = payload.get("job_id") or secrets.token_hex(8)
    if not _JOB_ID_RE.fullmatch(job_id):
        print(json.dumps({"error": "invalid_job_id",
                          "detail": "job_id must match ^[a-f0-9]{1,64}$"}),
              file=sys.stderr)
        sys.exit(2)
    return urls, spider_name, config, job_id


def _build_settings(config: dict[str, Any]) -> Any:
    settings = get_project_settings()
    # Resolve repo-relative SCRAPY_SETTINGS_MODULE via PYTHONPATH (handled at invocation).
    settings.setmodule("tools.scrapy_runner.project.settings")

    if "respect_robots" in config:
        settings.set("ROBOTSTXT_OBEY", bool(config["respect_robots"]), priority="cmdline")

    if config.get("session_id"):
        settings.set("SESSION_ID", config["session_id"], priority="cmdline")

    _log = logging.getLogger("scrapy_runner")
    for key, value in (config.get("settings") or {}).items():
        if key not in _SCRAPY_SETTINGS_WHITELIST:
            _log.warning(
                "settings_key_rejected: %s (not in whitelist)", key
            )
            continue
        settings.set(key, value, priority="cmdline")

    return settings


_RISK_DB_PATH = Path(__file__).parents[2] / "storage" / "risk_db.sqlite"


def _get_job_scores(job_id: str) -> list[tuple[float, str]]:
    """Return list of (risk_score, vendors_json) rows for a job_id from SQLite."""
    try:
        conn = sqlite3.connect(str(_RISK_DB_PATH))
        try:
            cur = conn.execute(
                "SELECT risk_score, vendors_json FROM risk_events WHERE job_id = ?",
                (job_id,),
            )
            return cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []


def _build_escalation(job_id: str, urls: list[str]) -> dict:
    """Query risk_events for this job and compute escalation hint."""
    rows = _get_job_scores(job_id)

    if not rows:
        return {
            "needed": False,
            "reason": "no_risk_data",
            "suggested_tool": None,
            "vendors_detected": [],
            "trigger_threshold": 0.5,
        }

    scores = [r[0] for r in rows]
    all_vendors: set[str] = set()
    for _, vj in rows:
        try:
            all_vendors.update(json.loads(vj or "[]"))
        except Exception:
            pass

    avg_risk = sum(scores) / len(scores)
    max_risk = max(scores)
    high_risk_count = sum(1 for s in scores if s >= 0.5)
    # trigger_min_responses=3 applies to the percentage check only;
    # a single response with max_risk >= 0.8 always escalates.
    pct_trigger = len(scores) >= 3 and (high_risk_count / len(scores) >= 0.5)
    needed = pct_trigger or (max_risk >= 0.8) or (avg_risk >= 0.5)

    if avg_risk >= 0.8 or max_risk == 1.0:
        suggested_tool = "screenshot"
    elif needed:
        suggested_tool = "crawl4ai"
    else:
        suggested_tool = None

    reason = (
        f"risk_score {max_risk:.2f} on {high_risk_count} of {len(scores)} requests"
        if needed else f"avg_risk {avg_risk:.2f} below threshold"
    )

    return {
        "needed": needed,
        "reason": reason,
        "suggested_tool": suggested_tool,
        "vendors_detected": sorted(all_vendors),
        "trigger_threshold": 0.5,
    }


def _persist_result(job_id: str, payload: dict[str, Any]) -> Path:
    s = get_settings()
    s.results_dir.mkdir(parents=True, exist_ok=True)
    out_path = s.results_dir / f"{job_id}.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp_path.replace(out_path)
    return out_path


def main(argv: list[str] | None = None) -> int:
    log = _setup_file_logging()
    payload = _read_input(argv if argv is not None else sys.argv[1:])
    urls, spider_name, config, job_id = _validate(payload)
    SpiderCls = _SPIDERS[spider_name]

    settings = _build_settings(config)
    started_at = _iso_now()
    t0 = time.perf_counter()

    log.info(json.dumps({"event": "run_started", "job_id": job_id, "spider": spider_name,
                          "urls": urls, "respect_robots": settings.getbool("ROBOTSTXT_OBEY")}))

    spider_kwargs: dict[str, Any] = {
        "urls": urls,
        "headers": config.get("headers") or {},
        "job_id": job_id,
    }
    if spider_name == "adaptive":
        spider_kwargs["selectors"] = config.get("selectors") or {}
        spider_kwargs["item_selector"] = config.get("item_selector")

    if spider_name == "ebay_browse":
        from bridge.config import get_settings as _get_bridge_settings
        _bs = _get_bridge_settings()
        spider_kwargs["q"] = config.get("q", "")
        spider_kwargs["marketplace_id"] = config.get("marketplace_id", getattr(_bs, "ebay_default_marketplace", "EBAY_FR"))
        spider_kwargs["max_pages"] = int(config.get("max_pages", 3))
        spider_kwargs["ebay_app_ids"] = config.get("ebay_app_ids") or getattr(_bs, "ebay_app_ids", [])
        spider_kwargs["ebay_cert_ids"] = config.get("ebay_cert_ids") or getattr(_bs, "ebay_cert_ids", [])

    if spider_name == "watchcount":
        spider_kwargs["q"] = config.get("q", "")
        spider_kwargs["marketplace"] = config.get("marketplace", "EBAY_FR")

    if spider_name == "2ememain":
        spider_kwargs["q"] = config.get("q", "")
        spider_kwargs["max_pages"] = int(config.get("max_pages", 3))

    if spider_name == "vinted":
        from bridge.config import get_settings as _get_bridge_settings_v
        _bsv = _get_bridge_settings_v()
        spider_kwargs["q"] = config.get("q", "")
        spider_kwargs["marketplace"] = config.get("marketplace", "FR")
        spider_kwargs["max_pages"] = int(config.get("max_pages", 3))
        spider_kwargs["groq_api_key"] = config.get("groq_api_key") or getattr(_bsv, "groq_api_key", "")

    process = CrawlerProcess(settings=settings, install_root_handler=False)
    crawler = process.create_crawler(SpiderCls)
    process.crawl(crawler, **spider_kwargs)
    try:
        process.start()  # blocks until crawl finishes
    except Exception as e:
        log.exception("scrapy_runtime_crash")
        print(json.dumps({"error": "scrapy_crash", "detail": str(e)}), file=sys.stderr)
        return 3

    spider = crawler.spider
    items = getattr(spider, "_collected_items", []) or []
    final_status = getattr(spider, "_final_http_status", None) or 0
    recaptcha_detected = getattr(spider, "_recaptcha_detected", False)
    blocked = getattr(spider, "_blocked", False)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    finished_at = _iso_now()

    job_scores = _get_job_scores(job_id)
    scores = [r[0] for r in job_scores]

    result = {
        "tool": "scrapy",
        "url": payload["url"],  # echo exactly what was sent in
        "http_status": final_status,
        "proxy": config.get("proxy"),
        "risk_score": max(scores) if scores else 0.0,
        "items": items,
        "_meta": {
            "spider": spider_name,
            "job_id": job_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "item_count": len(items),
            "recaptcha_detected": recaptcha_detected,
            "blocked": blocked,
        },
        "_escalation": _build_escalation(job_id, urls),
    }

    out_path = _persist_result(job_id, result)
    log.info(json.dumps({"event": "run_finished", "job_id": job_id,
                          "duration_ms": duration_ms, "item_count": len(items),
                          "http_status": final_status, "out_path": str(out_path)}))

    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
