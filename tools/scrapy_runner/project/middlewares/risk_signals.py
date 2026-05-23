"""Runtime risk scoring middleware — analyses each Scrapy response for WAF signals."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from tools.common.block_indicators import BLOCK_INDICATORS, WAF_VENDORS, CHALLENGE_KEYS

logger = structlog.get_logger(__name__)

_DB_PATH = Path(__file__).parents[4] / "storage" / "risk_db.sqlite"
_BLOCK_STATUS = {403, 429, 503, 520, 522, 524}
_SOFT_BLOCK_STATUS = {503, 520, 522, 524}
_HARD_BLOCK_STATUS = {403, 429}


def _init_risk_events_table(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS risk_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT,
                domain          TEXT NOT NULL,
                url             TEXT NOT NULL,
                ts              TEXT NOT NULL,
                http_status     INTEGER,
                risk_score      REAL NOT NULL,
                vendors_json    TEXT,
                markers_json    TEXT,
                response_size   INTEGER,
                duration_ms     INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_risk_events_domain ON risk_events(domain);
            CREATE INDEX IF NOT EXISTS idx_risk_events_ts ON risk_events(ts);
            CREATE INDEX IF NOT EXISTS idx_risk_events_job ON risk_events(job_id);
        """)
        conn.commit()
    finally:
        conn.close()


_init_risk_events_table(_DB_PATH)


def _detect_vendors(headers_str: str, body_snippet: str) -> dict[str, list[str]]:
    """Return dict of detected vendor -> matching markers."""
    combined = (headers_str + body_snippet).lower()
    detected: dict[str, list[str]] = {}
    for vendor, markers in BLOCK_INDICATORS.items():
        hits = [m for m in markers if m in combined]
        if hits:
            detected[vendor] = hits
    return detected


def _compute_risk_score(
    status: int,
    vendors_detected: dict[str, list[str]],
    markers: dict[str, int],
    response_size: int,
) -> float:
    score = 0.0
    waf_vendors = [v for v in vendors_detected if v in WAF_VENDORS]
    score += min(len(waf_vendors) * 0.20, 0.60)
    if status in _HARD_BLOCK_STATUS:
        score += 0.30
    elif status in _SOFT_BLOCK_STATUS:
        score += 0.20
    if markers.get("captcha", 0) > 0:
        score += 0.25
    if markers.get("botdet", 0) > 0:
        score += 0.15
    if 0 < response_size < 2000:
        score += 0.10
    return min(score, 1.0)


class RiskMiddleware:
    """Scrapy downloader middleware — scores risk on every response."""

    def __init__(self, risk_threshold_warn: float = 0.5,
                 risk_threshold_block: float = 0.8):
        self.threshold_warn = risk_threshold_warn
        self.threshold_block = risk_threshold_block

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            risk_threshold_warn=crawler.settings.getfloat("RISK_THRESHOLD_WARN", 0.5),
            risk_threshold_block=crawler.settings.getfloat("RISK_THRESHOLD_BLOCK", 0.8),
        )

    def process_response(self, request, response, spider):
        t0 = request.meta.get("_risk_t0") or time.perf_counter()
        duration_ms = int((time.perf_counter() - t0) * 1000)

        body_snippet = response.text[:50000] if hasattr(response, "text") else ""
        headers_str = "\n".join(
            f"{k.decode('utf-8', errors='replace')}: {v.decode('utf-8', errors='replace')}"
            for k, vals in response.headers.items()
            for v in vals
        )
        response_size = len(response.body) if response.body else 0

        vendors_detected = _detect_vendors(headers_str, body_snippet)

        markers: dict[str, int] = {
            "waf": len([v for v in vendors_detected if v in WAF_VENDORS]),
            "captcha": len([v for v in vendors_detected if v == "captcha"]),
            "botdet": len([v for v in vendors_detected if v == "botdet"]),
            "status": 1 if response.status in _BLOCK_STATUS else 0,
        }

        risk_score = _compute_risk_score(
            response.status, vendors_detected, markers, response_size
        )

        vendor_names = list(vendors_detected.keys())
        block_vendor = vendor_names[0] if vendor_names else None

        request.meta["risk_score"] = risk_score
        request.meta["block_vendor"] = block_vendor

        domain = _extract_domain(request.url)
        job_id = spider.crawler.stats.get_value("job_id") if hasattr(spider, "crawler") else None
        if not job_id:
            job_id = getattr(spider, "job_id", None)

        logger.info(
            "risk_signal",
            url=request.url,
            domain=domain,
            http_status=response.status,
            risk_score=risk_score,
            vendors=vendor_names,
            job_id=job_id,
        )

        self._persist(
            job_id=job_id,
            domain=domain,
            url=request.url,
            http_status=response.status,
            risk_score=risk_score,
            vendors_json=json.dumps(vendor_names),
            markers_json=json.dumps(markers),
            response_size=response_size,
            duration_ms=duration_ms,
        )

        return response

    def _persist(self, **kwargs) -> None:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.execute(
                    """
                    INSERT INTO risk_events
                        (job_id, domain, url, ts, http_status, risk_score,
                         vendors_json, markers_json, response_size, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kwargs.get("job_id"),
                        kwargs["domain"],
                        kwargs["url"],
                        ts,
                        kwargs.get("http_status"),
                        kwargs["risk_score"],
                        kwargs.get("vendors_json"),
                        kwargs.get("markers_json"),
                        kwargs.get("response_size"),
                        kwargs.get("duration_ms"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("risk_persist_failed", error=str(exc))


def _extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or url
    except Exception:
        return url
