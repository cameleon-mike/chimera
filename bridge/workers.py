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


def _run_screenshot_subprocess(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    """Invoke the screenshot runner as a subprocess.

    Same isolation rationale as Scrapy: Playwright state (browser processes,
    async loops) must not bleed into the RQ worker process.
    CLI contract: JSON on stdin, JSON on stdout, exit codes 0/2/3.
    """
    payload = {"job_id": job_id, "url": url, **config}
    cmd = [sys.executable, "-m", "tools.screenshot_runner.run_screenshot"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"screenshot runner exited {proc.returncode}: {stderr[-500:] or '<empty stderr>'}"
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("screenshot runner produced empty stdout")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"screenshot runner stdout is not valid JSON: {exc}") from exc


def _run_crawl4ai_subprocess(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    """Invoke the Crawl4AI runner as a subprocess.

    Same isolation rationale as Scrapy and screenshot: async event-loop state,
    Playwright browser processes and Chromium instances must not bleed into the
    RQ worker process.
    CLI contract: JSON on stdin, JSON on stdout, exit codes 0/2/3.
    """
    payload = {"job_id": job_id, "url": url, **config}
    cmd = [sys.executable, "-m", "tools.crawl4ai_runner.run_crawl4ai"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"crawl4ai runner exited {proc.returncode}: {stderr[-500:] or '<empty stderr>'}"
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("crawl4ai runner produced empty stdout")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"crawl4ai runner stdout is not valid JSON: {exc}") from exc


def _run_firecrawl_subprocess(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    """Invoke the Firecrawl runner as a subprocess.

    Same isolation rationale as Scrapy/screenshot/crawl4ai: the httpx async
    connections and potential event-loop state inside run_firecrawl must not
    bleed into the RQ worker process.
    CLI contract: JSON on stdin, JSON on stdout, exit codes 0/2/3.
    """
    from .config import get_settings

    settings = get_settings()
    payload = {
        "job_id": job_id,
        "url": url,
        "firecrawl_url": settings.firecrawl_url,
        "firecrawl_api_key": settings.firecrawl_api_key,
        **config,
    }
    cmd = [sys.executable, "-m", "tools.firecrawl_runner.run_firecrawl"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"firecrawl runner exited {proc.returncode}: {stderr[-500:] or '<empty stderr>'}"
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("firecrawl runner produced empty stdout")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"firecrawl runner stdout is not valid JSON: {exc}") from exc


def _run_bypass_subprocess(job_id: str, url, config: dict[str, Any]) -> dict[str, Any]:
    from .config import get_settings
    settings = get_settings()
    payload = {
        "job_id": job_id,
        "url": url,
        "flaresolverr_url": settings.flaresolverr_url,
        **config,
    }
    cmd = [sys.executable, "-m", "tools.waf_bypass.run_bypass"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"bypass_waf runner exited {proc.returncode}: {stderr[-500:] or '<empty stderr>'}"
        )
    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("bypass_waf runner produced empty stdout")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bypass_waf runner stdout is not valid JSON: {exc}") from exc


_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "scrapy":     _run_scrapy_subprocess,
    "screenshot": _run_screenshot_subprocess,
    "crawl4ai":   _run_crawl4ai_subprocess,
    "firecrawl":  _run_firecrawl_subprocess,
    "bypass_waf": _run_bypass_subprocess,
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
    _escalation = result.get("_escalation") or {}
    if _escalation.get("needed"):
        write_audit({
            "ts": _iso_now(),
            "event": "escalation_triggered",
            "job_id": job_id,
            "tool": tool,
            "suggested_tool": _escalation.get("suggested_tool"),
            "vendors_detected": _escalation.get("vendors_detected", []),
            "reason": _escalation.get("reason"),
        })
        logger.warning(
            "escalation_triggered",
            job_id=job_id,
            current_tool=tool,
            suggested_tool=_escalation.get("suggested_tool"),
            reason=_escalation.get("reason"),
        )
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
