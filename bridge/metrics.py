"""Prometheus metrics for the Chimera bridge."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram

_RISK_DB_PATH = Path(__file__).parent.parent / "storage" / "risk_db.sqlite"

requests_total = Counter(
    "chimera_requests_total",
    "Total HTTP requests handled by the bridge.",
    ["endpoint", "status_code"],
)
request_duration_seconds = Histogram(
    "chimera_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["endpoint"],
)
scrape_items_total = Counter(
    "chimera_scrape_items_total",
    "Total items scraped.",
    ["source"],
)
scrape_errors_total = Counter(
    "chimera_scrape_errors_total",
    "Total scrape errors.",
    ["source", "error_type"],
)
epid_stats_count = Gauge(
    "chimera_epid_stats_count",
    "Number of ePIDs tracked in epid_stats.",
)
profiles_count = Gauge(
    "chimera_profiles_count",
    "Number of browser profiles by status.",
    ["status"],
)
jobs_queued = Gauge(
    "chimera_jobs_queued",
    "Number of jobs queued in RQ.",
)
jobs_active = Gauge(
    "chimera_jobs_active",
    "Number of jobs currently active in RQ.",
)


def collect_runtime_gauges() -> None:
    """Refresh gauge values from SQLite + Redis. Best-effort; never raises."""
    try:
        conn = sqlite3.connect(str(_RISK_DB_PATH))
        try:
            epids = conn.execute("SELECT COUNT(*) FROM epid_stats").fetchone()[0] or 0
            epid_stats_count.set(epids)
            seen = set()
            for status, cnt in conn.execute(
                "SELECT status, COUNT(*) FROM profiles GROUP BY status"
            ).fetchall():
                label = status or "unknown"
                profiles_count.labels(status=label).set(cnt)
                seen.add(label)
            for status in ("creating", "warming", "ready", "senior", "recycle"):
                if status not in seen:
                    profiles_count.labels(status=status).set(0)
        finally:
            conn.close()
    except Exception:
        pass
    try:
        from rq import Queue
        from rq.registry import StartedJobRegistry
        from bridge import queue as q

        redis_conn = q._redis_conn()
        queued = 0
        active = 0
        for qname in ("high", "normal", "low"):
            queued += Queue(qname, connection=redis_conn).count
            active += len(StartedJobRegistry(qname, connection=redis_conn))
        jobs_queued.set(queued)
        jobs_active.set(active)
    except Exception:
        pass
