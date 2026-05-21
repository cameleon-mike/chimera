"""RQ worker entrypoint and per-tool dispatch table.

The single RQ-callable function is `dispatch_job(...)`. It:
  1. emits a `job_started` audit event
  2. looks up the tool in `_DISPATCH` and calls it
  3. on success: emits `job_finished` with latency_ms, result_size,
     http_status, proxy, risk_score; persists to storage/results/{job_id}.json
  4. on failure: emits `job_failed` with error_class + error_msg and re-raises
     so RQ marks the job FAILED.

Each per-tool function for Step 1.3 is a **stub** that simulates work and
returns a realistically-shaped dict. Real runners replace the stubs:
  - scrapy     → Step 1.4
  - screenshot → Step 3.2
  - crawl4ai   → Step 3.3
  - firecrawl  → Step 3.4
  - bypass_waf → Step 3.5
The `probe` tool is NOT routed through RQ — it has its own synchronous
endpoint (`/probe/{domain}`, Step 2.1).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import manifest as mf
from .logging_setup import setup_logging, write_audit
from .queue import save_result


# --- Logger init (TD-2 — module-level idempotent guard) ----------------------
# setup_logging() was previously called inside dispatch_job() on every job,
# which is wasteful and fragile under concurrent workers. We initialise once
# at module load (each RQ worker process imports this module on startup) and
# expose `_ensure_logger()` for any future callsites that might be reached
# before module load completes (none today, but cheap insurance).

_LOGGER = None


def _ensure_logger():
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = setup_logging()
    return _LOGGER


# Eagerly initialise on import so the worker process has a logger ready
# before the first job is picked up.
_ensure_logger()


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --- Stub implementations (Step 1.3) -----------------------------------------


def _run_scrapy_subprocess(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    """Invoke the standalone Scrapy runner as a subprocess.

    Why subprocess and not in-process? The Twisted reactor used by Scrapy
    cannot be restarted within the same Python process, which would limit
    each RQ worker to a single crawl per process lifetime. Forking a fresh
    interpreter per job costs ~500 ms-1 s of startup but gives us full
    isolation — runner crashes don't poison the worker, and reactor state
    is always pristine.

    The subprocess reuses tools.scrapy_runner.run_scrapy's CLI contract:
    JSON in on stdin, JSON out on stdout, exit codes 0/2/3.
    """
    payload = {
        "tool": "scrapy",
        "url": url,
        "config": config,
        "job_id": job_id,
    }
    cmd = [sys.executable, "-m", "tools.scrapy_runner.run_scrapy"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    if proc.returncode != 0:
        # Surface stderr (JSON-encoded error dict from the runner) so RQ
        # captures a useful message in job.exc_info.
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"scrapy runner exited {proc.returncode}: {stderr or '<empty stderr>'}"
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("scrapy runner produced empty stdout")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"scrapy runner stdout is not valid JSON: {e}") from e


def _stub_screenshot(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    time.sleep(0.3)
    return {
        "tool": "screenshot",
        "url": url,
        "http_status": 200,
        "proxy": config.get("proxy"),
        "risk_score": 0.85,
        "screenshot_path": f"storage/screenshots/{job_id}.png",
        "_stub": True,
    }


def _stub_crawl4ai(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    time.sleep(0.3)
    return {
        "tool": "crawl4ai",
        "url": url,
        "http_status": 200,
        "proxy": config.get("proxy"),
        "risk_score": 0.45,
        "markdown": "# Stub\nStep 3.3 lands the real Crawl4AI runner.",
        "_stub": True,
    }


def _stub_firecrawl(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    time.sleep(0.3)
    return {
        "tool": "firecrawl",
        "url": url,
        "http_status": 200,
        "proxy": None,
        "risk_score": 0.30,
        "markdown": "# Stub\nStep 3.4 lands the real Firecrawl runner.",
        "_stub": True,
    }


def _stub_bypass_waf(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    time.sleep(0.3)
    return {
        "tool": "bypass_waf",
        "url": url,
        "http_status": 200,
        "proxy": None,
        "risk_score": 0.95,
        "challenge_solved": True,
        "_stub": True,
    }


_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "scrapy":     _run_scrapy_subprocess,
    "screenshot": _stub_screenshot,
    "crawl4ai":   _stub_crawl4ai,
    "firecrawl":  _stub_firecrawl,
    "bypass_waf": _stub_bypass_waf,
}


# --- Entrypoint --------------------------------------------------------------


def dispatch_job(
    job_id: str,
    tool: str,
    url,
    config: dict[str, Any],
    callback_url: str | None = None,
) -> dict[str, Any]:
    """Called by every RQ worker. Returns the runner's result dict on success;
    raises on failure so RQ marks the job FAILED."""

    logger = _ensure_logger()
    started_at = time.perf_counter()
    started_ts = _iso_now()

    write_audit({
        "ts": started_ts,
        "event": "job_started",
        "job_id": job_id,
        "tool": tool,
        "url": url if isinstance(url, str) else (url[0] if url else None),
    })
    logger.info("job_started", job_id=job_id, tool=tool)

    runner = _DISPATCH.get(tool)
    if runner is None:
        # Tool is in manifest but not RQ-dispatchable (e.g. probe), or unknown.
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        err = f"tool {tool!r} is not dispatched through RQ (check tool_manifest.json)"
        write_audit({
            "ts": _iso_now(), "event": "job_failed", "job_id": job_id, "tool": tool,
            "latency_ms": latency_ms, "error_class": "DispatchError", "error_msg": err,
        })
        raise ValueError(err)

    try:
        result = runner(job_id, url, config)
    except Exception as e:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        write_audit({
            "ts": _iso_now(), "event": "job_failed", "job_id": job_id, "tool": tool,
            "latency_ms": latency_ms,
            "error_class": type(e).__name__, "error_msg": str(e),
        })
        logger.error("job_failed", job_id=job_id, tool=tool, error_class=type(e).__name__, error_msg=str(e))
        raise

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    save_result(job_id, result)
    result_blob = json.dumps(result, separators=(",", ":"))

    write_audit({
        "ts": _iso_now(),
        "event": "job_finished",
        "job_id": job_id,
        "tool": tool,
        "latency_ms": latency_ms,
        "result_size": len(result_blob),
        "http_status": result.get("http_status"),
        "proxy": result.get("proxy"),
        "risk_score": result.get("risk_score"),
    })
    logger.info("job_finished",
                job_id=job_id, tool=tool, latency_ms=latency_ms,
                result_size=len(result_blob),
                http_status=result.get("http_status"),
                risk_score=result.get("risk_score"))
    return result
