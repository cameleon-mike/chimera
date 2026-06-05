"""FastAPI bridge — entrypoint for cameleon.

Step 1.2: skeletons of all 6 endpoints, auth wired, structured logging.
Step 1.3 will replace the stubs with real RQ enqueue / status / result.
Step 2.3 will implement /risk/{domain}.
Step 3.2 will implement /download/{job_id}.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from . import __version__, manifest as mf
from .auth import require_bearer
from .config import get_settings
from .logging_setup import setup_logging, write_audit
from . import queue as q
from .schemas import (
    AggregateSearchResponse,
    AggregatedItem,
    DailyRunResponse,
    EbayItem,
    EbayPrice,
    EbaySearchResponse,
    EpidStats,
    EscalateRequest,
    EscalateResponse,
    FactoryStatsResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    JobStatus,
    ProfileCreateRequest,
    ProfileResponse,
    ProbeResponse,
    ResultResponse,
    RiskResponse,
    RunToolRequest,
    RunToolResponse,
    StatusResponse,
    TwoememainItem,
    TwoememainSearchResponse,
    VintedSearchResponse,
    WatchCountItem,
    WatchCountSearchResponse,
)
from tools.common.domain_validator import validate_fqdn

logger = setup_logging()
settings = get_settings()

_RISK_DB_PATH = Path(__file__).parent.parent / "storage" / "risk_db.sqlite"


def _init_risk_db() -> None:
    conn = sqlite3.connect(str(_RISK_DB_PATH))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS domain_probe (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                domain          TEXT NOT NULL,
                probed_at       TEXT NOT NULL,
                risk_score      REAL NOT NULL,
                vendors_json    TEXT,
                indicators_json TEXT,
                features_json   TEXT,
                tls_version     TEXT,
                tls_cipher      TEXT,
                http_status     INTEGER,
                recommendation_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_domain_probe_domain ON domain_probe(domain);
            CREATE INDEX IF NOT EXISTS idx_domain_probe_probed_at ON domain_probe(probed_at);
            CREATE TABLE IF NOT EXISTS proxy_use (
                proxy_url TEXT,
                host      TEXT,
                ts        INTEGER,
                status    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_proxy_use_lookup ON proxy_use(proxy_url, host, ts);
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
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id          TEXT PRIMARY KEY,
                geo_id              TEXT NOT NULL DEFAULT 'fr-paris',
                proxy_country       TEXT NOT NULL DEFAULT 'FR',
                ua_profile_id       TEXT NOT NULL DEFAULT 'chrome127-win',
                status              TEXT DEFAULT 'created',
                age_days            INTEGER DEFAULT 0,
                created_at          TEXT,
                last_active         TEXT,
                last_used           TEXT,
                warmed              INTEGER DEFAULT 0,
                cookies_count       INTEGER DEFAULT 0,
                extensions_json     TEXT DEFAULT '[]',
                linked_account_json TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_profiles_status ON profiles(status);
            CREATE INDEX IF NOT EXISTS idx_profiles_country ON profiles(proxy_country);
            CREATE TABLE IF NOT EXISTS epid_stats (
                epid            TEXT PRIMARY KEY,
                brand           TEXT,
                model           TEXT,
                total_items     INTEGER DEFAULT 0,
                currency        TEXT,
                median_price    REAL,
                q1_price        REAL,
                q2_price        REAL,
                q3_price        REAL,
                q4_price        REAL,
                avg_sell_days   REAL,
                min_sell_days   REAL,
                max_sell_days   REAL,
                sell_days_sample INTEGER DEFAULT 0,
                last_updated    TEXT
            );
            CREATE TABLE IF NOT EXISTS scraped_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                epid            TEXT,
                title           TEXT,
                price_value     REAL,
                price_currency  TEXT,
                start_date      TEXT,
                end_date        TEXT,
                source          TEXT,
                url             TEXT UNIQUE,
                scraped_at      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_scraped_items_epid ON scraped_items(epid);
        """)
        conn.commit()
    finally:
        conn.close()


_init_risk_db()

from bridge.scheduler import setup_scheduler  # noqa: E402

app = FastAPI(
    title="Chimera",
    version=__version__,
    description=(
        "Hybrid production scraper, piloted by cameleon. "
        "All configurable options are discoverable via /capabilities (the live "
        "tool_manifest.json) and /openapi.json. Cameleon decides; chimera executes."
    ),
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

setup_scheduler(app, settings)


# --- Request logging middleware --------------------------------------


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
        client=request.client.host if request.client else None,
    )
    return response


# --- Endpoints -------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness probe — no auth. Returns manifest + bridge versions."""
    return HealthResponse(
        status="ok",
        manifest_version=mf.manifest_version(),
        bridge_version=__version__,
    )


@app.get("/capabilities", tags=["meta"])
async def capabilities():
    """Serve the full tool_manifest.json — cameleon's primary discovery surface.

    No auth: this is read-only metadata about what chimera can do. The actual
    job-submission endpoints below require Bearer auth.
    """
    return {"schema_version": "1.0", **mf.load_manifest()}


@app.post("/run-tool", response_model=RunToolResponse, tags=["jobs"])
async def run_tool(
    req: RunToolRequest,
    _token: Annotated[str, Depends(require_bearer)],
) -> RunToolResponse:
    """Accept a scraping job, enqueue on the matching RQ queue, return job_id."""
    job_id = uuid.uuid4().hex[:16]
    tool_name = req.tool.value if hasattr(req.tool, "value") else str(req.tool)

    q.enqueue_job(
        job_id=job_id,
        tool=tool_name,
        url=req.url,
        config=req.config,
        priority=req.priority,
        callback_url=req.callback_url,
    )

    logger.info(
        "run_tool_accepted",
        job_id=job_id, tool=tool_name, priority=req.priority.value,
        url=req.url if isinstance(req.url, str) else f"<list len={len(req.url)}>",
    )
    write_audit({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "run_tool_accepted",
        "job_id": job_id,
        "tool": tool_name,
        "priority": req.priority.value,
        "url": req.url if isinstance(req.url, str) else req.url[0],
    })
    return RunToolResponse(job_id=job_id, status=JobStatus.queued)


@app.get("/status/{job_id}", response_model=StatusResponse, tags=["jobs"])
async def get_status(
    job_id: str,
    _token: Annotated[str, Depends(require_bearer)],
) -> StatusResponse:
    """Live job status from RQ."""
    job = q.fetch_job(job_id)
    if job is None:
        return StatusResponse(job_id=job_id, status=JobStatus.not_found)
    args = job.args or ()
    tool = args[1] if len(args) >= 2 else None
    return StatusResponse(
        job_id=job_id,
        status=q.map_status(job.get_status()),
        tool=tool,
        enqueued_at=job.enqueued_at.isoformat() if job.enqueued_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.ended_at.isoformat() if job.ended_at else None,
    )


@app.get("/result/{job_id}", response_model=ResultResponse, tags=["jobs"])
async def get_result(
    job_id: str,
    _token: Annotated[str, Depends(require_bearer)],
) -> ResultResponse:
    """Return the persisted result (canonical store: storage/results/{id}.json).
    Falls back to the RQ return value if the file is missing."""
    job = q.fetch_job(job_id)
    if job is None:
        return ResultResponse(job_id=job_id, status=JobStatus.not_found)

    status = q.map_status(job.get_status())
    if status == JobStatus.failed:
        return ResultResponse(
            job_id=job_id,
            status=status,
            error=str(job.exc_info).splitlines()[-1] if job.exc_info else "job failed",
        )
    if status != JobStatus.finished:
        return ResultResponse(job_id=job_id, status=status)

    payload = q.load_result(job_id) or job.return_value()
    return ResultResponse(job_id=job_id, status=JobStatus.finished, result=payload)


@app.get("/risk/{domain}", response_model=RiskResponse, tags=["risk"])
async def get_risk(
    domain: str,
    hours: int = 24,
    _token: Annotated[str, Depends(require_bearer)] = None,
) -> RiskResponse:
    """Aggregated risk history for a domain over last N hours."""
    _valid, _reason = validate_fqdn(domain)
    if not _valid:
        raise HTTPException(status_code=422, detail=_reason)

    conn = sqlite3.connect(str(_RISK_DB_PATH))
    try:
        cur = conn.execute(
            """
            SELECT risk_score, vendors_json, markers_json, http_status
            FROM risk_events
            WHERE domain = ?
              AND ts > datetime('now', ? || ' hours')
            ORDER BY ts DESC
            """,
            (domain, f"-{hours}"),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return RiskResponse(
            domain=domain,
            window_hours=hours,
            requests=0,
            blocks=0,
            captchas=0,
            avg_risk=0.0,
            max_risk=0.0,
            vendors_seen=[],
            recommendation="no_data",
        )

    scores = [r[0] for r in rows]
    avg_risk = sum(scores) / len(scores)
    max_risk = max(scores)
    blocks = sum(1 for r in rows if (r[3] or 0) in {403, 429, 503, 520, 522, 524})
    captchas = 0
    vendors_seen: set[str] = set()
    for _, vj, mj, _ in rows:
        try:
            vendors_seen.update(json.loads(vj or "[]"))
        except Exception:
            pass
        try:
            m = json.loads(mj or "{}")
            captchas += m.get("captcha", 0)
        except Exception:
            pass

    if avg_risk >= 0.8:
        recommendation = "start_with:screenshot"
    elif avg_risk >= 0.5:
        recommendation = "start_with:crawl4ai"
    elif avg_risk >= 0.2:
        recommendation = "start_with:scrapy_residential"
    else:
        recommendation = "start_with:scrapy_datacenter"

    return RiskResponse(
        domain=domain,
        window_hours=hours,
        requests=len(rows),
        blocks=blocks,
        captchas=captchas,
        avg_risk=round(avg_risk, 4),
        max_risk=round(max_risk, 4),
        vendors_seen=sorted(vendors_seen),
        recommendation=recommendation,
    )


@app.get("/probe/{domain}", response_model=ProbeResponse, tags=["risk"])
def probe_domain_endpoint(
    domain: str,
    force: bool = False,
    _token: Annotated[str, Depends(require_bearer)] = None,
) -> ProbeResponse:
    """Synchronous security probe. Cached 24h unless force=true."""
    _valid, _reason = validate_fqdn(domain)
    if not _valid:
        raise HTTPException(status_code=422, detail=_reason)

    conn = sqlite3.connect(str(_RISK_DB_PATH))
    try:
        if not force:
            cur = conn.execute(
                """
                SELECT domain, probed_at, risk_score, vendors_json, indicators_json,
                       features_json, tls_version, tls_cipher, http_status,
                       recommendation_json
                FROM domain_probe
                WHERE domain = ?
                  AND probed_at > datetime('now', '-24 hours')
                ORDER BY probed_at DESC
                LIMIT 1
                """,
                (domain,),
            )
            row = cur.fetchone()
            if row is not None:
                (
                    _domain, probed_at, risk_score, vendors_json, indicators_json,
                    features_json, tls_version, tls_cipher, http_status,
                    recommendation_json,
                ) = row
                rec_dict = json.loads(recommendation_json) if recommendation_json else {}
                return ProbeResponse(
                    domain=_domain,
                    probed_at=probed_at,
                    risk_score=risk_score,
                    vendors_detected=json.loads(vendors_json) if vendors_json else [],
                    tls={
                        "version": tls_version or "unknown",
                        "cipher": tls_cipher or "unknown",
                        "has_cert": False,
                    },
                    features=json.loads(features_json) if features_json else {},
                    indicators=json.loads(indicators_json) if indicators_json else {},
                    http_status=http_status or 0,
                    recommendation=rec_dict,
                    cached=True,
                )

        from tools.probe.security_probe import probe_domain as _probe_domain
        raw = _probe_domain(domain)

        rec = raw.get("recommendation", {})
        tls = raw.get("tls", {})

        conn.execute(
            """
            INSERT INTO domain_probe
                (domain, probed_at, risk_score, vendors_json, indicators_json,
                 features_json, tls_version, tls_cipher, http_status, recommendation_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw["domain"],
                raw["probed_at"],
                raw.get("risk_score") or 0.0,
                json.dumps(raw.get("vendors_detected", [])),
                json.dumps(raw.get("indicators", {})),
                json.dumps(raw.get("features", {})),
                tls.get("version"),
                tls.get("cipher"),
                raw.get("http_status", 0),
                json.dumps(rec),
            ),
        )
        conn.commit()

        return ProbeResponse(
            domain=raw["domain"],
            probed_at=raw["probed_at"],
            risk_score=raw.get("risk_score") or 0.0,
            vendors_detected=raw.get("vendors_detected", []),
            tls=tls,
            features=raw.get("features", {}),
            indicators=raw.get("indicators", {}),
            http_status=raw.get("http_status", 0),
            recommendation=rec,
            cached=False,
        )
    finally:
        conn.close()


def _compute_escalation(job_id: str) -> dict:
    """Query risk_events for job and compute escalation hint."""
    conn = sqlite3.connect(str(_RISK_DB_PATH))
    try:
        cur = conn.execute(
            "SELECT risk_score, vendors_json FROM risk_events WHERE job_id = ?",
            (job_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "job_id": job_id,
            "needed": False,
            "reason": "no_risk_data",
            "suggested_tool": None,
            "vendors_detected": [],
            "trigger_threshold": 0.5,
            "avg_risk": 0.0,
            "max_risk": 0.0,
            "response_count": 0,
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
        if needed
        else f"avg_risk {avg_risk:.2f} below threshold"
    )

    return {
        "job_id": job_id,
        "needed": needed,
        "reason": reason,
        "suggested_tool": suggested_tool,
        "vendors_detected": sorted(all_vendors),
        "trigger_threshold": 0.5,
        "avg_risk": round(avg_risk, 4),
        "max_risk": round(max_risk, 4),
        "response_count": len(scores),
    }


@app.post("/escalate", response_model=EscalateResponse, tags=["risk"])
async def escalate(
    req: EscalateRequest,
    _token: Annotated[str, Depends(require_bearer)],
) -> EscalateResponse:
    """Compute escalation recommendation for a completed scrapy job.

    Queries risk_events for the job_id and applies the escalation policy:
    avg_risk >= 0.8 → screenshot, >= 0.5 → crawl4ai, < 0.5 → not needed.
    """
    data = _compute_escalation(req.job_id)
    return EscalateResponse(**data)


@app.get("/escalation/policy", tags=["risk"])
async def escalation_policy_endpoint():
    """Serve the static escalation policy from tool_manifest.json.

    No auth required — this is read-only metadata.
    avg_risk >= 0.8 → screenshot, >= 0.5 → crawl4ai, < 0.5 → scrapy.
    """
    return mf.get_escalation_policy()


@app.get("/download/{job_id}", tags=["jobs"])
async def download_artifact(
    job_id: str,
    _token: Annotated[str, Depends(require_bearer)],
):
    """Binary download (PNG) for screenshot jobs."""
    png_path = settings.screenshots_dir / f"{job_id}.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(
        path=str(png_path),
        media_type="image/png",
        filename=f"{job_id}.png",
    )


# --- eBay search endpoint ----------------------------------------------------


@app.get("/ebay/search", response_model=EbaySearchResponse, tags=["ebay"])
async def ebay_search(
    q: str,
    marketplace: str = "EBAY_FR",
    max_pages: int = 3,
    ingest: bool = False,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> EbaySearchResponse:
    """Synchronous eBay Browse API search via Scrapy spider. Auth Bearer required."""
    if not getattr(settings, "ebay_app_ids", []):
        raise HTTPException(status_code=503, detail="eBay API keys not configured")

    import asyncio
    from datetime import datetime, timezone
    from .workers import _run_scrapy_subprocess

    job_id = uuid.uuid4().hex[:16]
    config = {
        "spider": "ebay_browse",
        "q": q,
        "marketplace_id": marketplace,
        "max_pages": max_pages,
        "respect_robots": False,
        "ebay_app_ids": getattr(settings, "ebay_app_ids", []),
        "ebay_cert_ids": getattr(settings, "ebay_cert_ids", []),
    }

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _run_scrapy_subprocess,
                job_id,
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                config,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="eBay search timed out after 120s")

    raw_items = result.get("items", [])
    items = []
    for raw in raw_items:
        price_data = raw.get("price")
        if isinstance(price_data, dict):
            price = EbayPrice(
                value=price_data.get("value"),
                currency=price_data.get("currency"),
            )
        else:
            price = None
        items.append(EbayItem(
            title=raw.get("title"),
            price=price,
            epid=raw.get("epid"),
            start_date=raw.get("start_date"),
            end_date=raw.get("end_date"),
            photo_url=raw.get("photo_url"),
            link=raw.get("link"),
        ))

    risk_score = result.get("risk_score", 0.0)

    if ingest and items:
        from tools.stats.epid_calculator import recompute_all_stats as _recompute
        _conn = sqlite3.connect(str(_RISK_DB_PATH))
        try:
            from datetime import datetime as _dt, timezone as _tz
            _now = _dt.now(_tz.utc).isoformat()
            for it in items:
                _url = it.link
                if not _url:
                    continue
                _conn.execute(
                    """
                    INSERT OR IGNORE INTO scraped_items
                        (epid, title, price_value, price_currency,
                         start_date, end_date, source, url, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        it.epid, it.title,
                        it.price.value if it.price else None,
                        it.price.currency if it.price else None,
                        it.start_date, it.end_date,
                        "ebay", _url, _now,
                    ),
                )
            _conn.commit()
            _recompute(_conn)
        finally:
            _conn.close()

    return EbaySearchResponse(
        query=q,
        marketplace=marketplace,
        total_items=len(items),
        items=items,
        api_calls_used=max_pages,
        risk_scores=[risk_score] if risk_score else [],
        ts=datetime.now(timezone.utc).isoformat(),
    )


# --- WatchCount endpoint ------------------------------------------------------


def _ingest_sold_dates(items_raw: list[dict]) -> None:
    """Best-effort ingest of sold dates from vision items into scraped_items."""
    try:
        from tools.stats.epid_calculator import recompute_all_stats
        conn = _get_epid_conn()
        updated_any = False
        for item in items_raw:
            title = item.get("title")
            end_date = item.get("end_date")
            if not title or not end_date:
                continue
            title_prefix = title[:40]
            conn.execute(
                "UPDATE scraped_items SET end_date = ? WHERE title LIKE ? AND end_date IS NULL",
                (end_date, f"%{title_prefix}%"),
            )
            if conn.total_changes > 0:
                updated_any = True
        conn.commit()
        if updated_any:
            recompute_all_stats(conn)
        conn.close()
    except Exception as exc:
        logger.warning("ingest_sold_dates_error: %s", repr(exc))


_WATCHCOUNT_MARKETPLACE_LANG: dict[str, str] = {
    "EBAY_FR": "fr",
    "EBAY_DE": "de",
    "EBAY_GB": "gb",
    "EBAY_BE": "fr",
    "EBAY_NL": "nl",
}


@app.get("/watchcount/search", response_model=WatchCountSearchResponse, tags=["watchcount"])
async def watchcount_search(
    q: str,
    marketplace: str = "EBAY_FR",
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> WatchCountSearchResponse:
    """WatchCount.com search: Scrapy first, auto-escalates to Screenshot+Groq Vision on reCAPTCHA."""
    import asyncio
    from datetime import datetime, timezone
    from urllib.parse import quote_plus
    from .workers import _run_scrapy_subprocess, _run_screenshot_subprocess

    lang = _WATCHCOUNT_MARKETPLACE_LANG.get(marketplace, "en")
    url = (
        "https://www.watchcount.com/listing.cgi"
        f"?lang={lang}&ldc=0&q={quote_plus(q)}&order=wc"
    )

    scrapy_job_id = uuid.uuid4().hex[:16]
    scrapy_config = {
        "spider": "watchcount",
        "q": q,
        "marketplace": marketplace,
        "respect_robots": False,
    }

    # Step 1: Try Scrapy spider
    tool_used = "scrapy"
    recaptcha_detected = False
    items_raw: list[dict] = []

    try:
        scrapy_result = await asyncio.wait_for(
            asyncio.to_thread(_run_scrapy_subprocess, scrapy_job_id, url, scrapy_config),
            timeout=60.0,
        )
        items_raw = scrapy_result.get("items", [])
        recaptcha_detected = scrapy_result.get("_meta", {}).get("recaptcha_detected", False)
    except asyncio.TimeoutError:
        logger.warning("watchcount_scrapy_timeout job_id=%s", scrapy_job_id)
        recaptcha_detected = True
    except Exception as exc:
        logger.warning("watchcount_scrapy_error: %s", repr(exc))
        recaptcha_detected = True

    # Step 2: Escalate to Screenshot + Groq Vision when reCAPTCHA or no items
    if recaptcha_detected or not items_raw:
        tool_used = "screenshot+groq_vision"
        try:
            ss_job_id = uuid.uuid4().hex[:16]
            ss_result = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_screenshot_subprocess,
                    ss_job_id,
                    url,
                    {"profile_id": "default", "wait_ms": 2000, "headless": True},
                ),
                timeout=90.0,
            )
            png_path = ss_result.get("screenshot_path")
            groq_key = settings.groq_api_key
            if png_path and Path(png_path).exists() and groq_key:
                from tools.vision_agent.extract_sold_dates import SoldDateExtractor
                extractor = SoldDateExtractor(groq_key)
                items_raw = extractor.extract_from_screenshot(png_path)
                tool_used = "screenshot+vision"
                # Ingest sold dates into epid_stats (best-effort, never crashes)
                if items_raw:
                    _ingest_sold_dates(items_raw)
            elif not groq_key:
                logger.warning("watchcount_groq_key_missing — screenshot taken but no vision extraction")
                tool_used = "screenshot_only"
            else:
                logger.warning("watchcount_screenshot_path_missing")
                tool_used = "screenshot_failed"
        except asyncio.TimeoutError:
            logger.warning("watchcount_screenshot_timeout")
            tool_used = "escalation_timeout"
        except Exception as exc:
            logger.warning("watchcount_escalation_error: %s", repr(exc))
            tool_used = "escalation_error"

    # Normalise items to WatchCountItem schema
    items = [
        WatchCountItem(
            title=raw.get("title"),
            watch_count=raw.get("watch_count"),
            end_date=raw.get("end_date"),
            price=raw.get("price"),
            ebay_url=raw.get("ebay_url"),
            ebay_item_id=raw.get("ebay_item_id"),
            source=raw.get("source", "watchcount"),
        )
        for raw in items_raw
    ]

    return WatchCountSearchResponse(
        query=q,
        marketplace=marketplace,
        total_items=len(items),
        items=items,
        tool_used=tool_used,
        recaptcha_detected=recaptcha_detected,
        ts=datetime.now(timezone.utc).isoformat(),
    )


# --- Profile factory endpoints -----------------------------------------------


def _get_factory():
    """Instantiate AccountFactory bound to the global risk_db and cookies_dir."""
    from tools.account_factory.factory import AccountFactory
    return AccountFactory(
        db_path=settings.risk_db_path,
        profiles_dir=settings.cookies_dir,
        settings=settings,
    )


@app.get("/factory/profiles", tags=["factory"])
async def list_factory_profiles(
    status: str | None = None,
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """List all registered browser profiles, optionally filtered by status."""
    factory = _get_factory()
    profiles = factory.list_all_profiles()
    if status:
        profiles = [p for p in profiles if p.get("status") == status]
    return {"profiles": profiles}


@app.get("/factory/profiles/{profile_id}", tags=["factory"])
async def get_factory_profile(
    profile_id: str,
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """Retrieve a single profile by ID."""
    factory = _get_factory()
    profile = factory._get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@app.post("/factory/create", tags=["factory"])
async def create_factory_profiles(
    body: ProfileCreateRequest,
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """Create N profiles with status=creating."""
    from tools.account_factory.profile_config import ProfileConfig
    factory = _get_factory()
    created = []
    for _ in range(body.count):
        config = ProfileConfig(
            geo_id=body.geo_id,
            proxy_country=body.proxy_country,
            ua_profile_id=body.ua_profile_id,
        )
        pid = factory.create_profile(config)
        created.append(pid)
    return {"created": created, "count": len(created)}


@app.post("/factory/warm/{profile_id}", tags=["factory"])
async def warm_factory_profile(
    profile_id: str,
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """Launch the warm-up sequence for a profile (10–15 min, runs inline)."""
    factory = _get_factory()
    result = await factory.run_warm_up(profile_id)
    return result


@app.post("/factory/run-daily", tags=["factory"])
async def run_daily_factory(
    body: dict = {},
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """Trigger the full daily factory orchestration (create + warm + age)."""
    factory = _get_factory()
    new_count = body.get("new_profiles_count", settings.factory_new_profiles_per_day)
    report = await factory.daily_factory_run(new_profiles_count=new_count)
    return report


@app.get("/factory/stats", tags=["factory"])
async def factory_stats(
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """Return profile counts by status."""
    factory = _get_factory()
    return factory.get_stats()


@app.get("/factory/recommend", tags=["factory"])
async def recommend_factory_profile(
    domain: str,
    _token: Annotated[str, Depends(require_bearer)] = ...,
):
    """Return the best warmed profile for a domain (geo-coherent, highest age)."""
    _valid, _reason = validate_fqdn(domain)
    if not _valid:
        raise HTTPException(status_code=422, detail=_reason)
    factory = _get_factory()
    profile = factory.get_best_for_domain(domain)
    if not profile:
        raise HTTPException(status_code=404, detail="no ready profile found")
    return profile


# --- 2ememain.be search endpoint --------------------------------------------


@app.get("/2ememain/search", response_model=TwoememainSearchResponse, tags=["2ememain"])
async def search_2ememain(
    q: str,
    max_pages: int = 3,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> TwoememainSearchResponse:
    """Synchronous 2ememain.be search via Scrapy spider. Auth Bearer required.

    Returns listings CSV-compatible with /ebay/search (EbayPrice, start_date, end_date).
    When the site blocks scrapy (403/429/captcha), returns items=[] and blocked=True.
    """
    import asyncio
    from datetime import datetime, timezone
    from .workers import _run_scrapy_subprocess, _run_screenshot_subprocess

    job_id = uuid.uuid4().hex[:16]
    url = f"https://www.2ememain.be/q/{q}/"
    config = {
        "spider": "2ememain",
        "q": q,
        "max_pages": max_pages,
        "respect_robots": False,
    }

    try:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_scrapy_subprocess, job_id, url, config),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="2ememain search timed out after 120s")

        raw_items = result.get("items", [])
        blocked = result.get("_meta", {}).get("blocked", False)
        tool_used = "scrapy"

        # Escalade vers Screenshot + Groq Vision quand le site bloque (403/429)
        if blocked:
            try:
                ss_job_id = uuid.uuid4().hex[:16]
                ss_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        _run_screenshot_subprocess,
                        ss_job_id,
                        url,
                        {"profile_id": "default", "wait_ms": 2000, "headless": True},
                    ),
                    timeout=90.0,
                )
                png_path = ss_result.get("screenshot_path")
                groq_key = settings.groq_api_key
                if png_path and Path(png_path).exists() and groq_key:
                    from tools.groq_vision.extract_dates import GroqVisionExtractor
                    extractor = GroqVisionExtractor(groq_key)
                    raw_items = extractor.extract_items(png_path, query=q)
                    tool_used = "screenshot+groq_vision"
                elif not groq_key:
                    logger.warning("2ememain_groq_key_missing — screenshot taken but no vision extraction")
                    tool_used = "screenshot_only"
                else:
                    logger.warning("2ememain_screenshot_path_missing")
                    tool_used = "screenshot_failed"
            except asyncio.TimeoutError:
                logger.warning("2ememain_screenshot_timeout")
                tool_used = "escalation_timeout"
            except Exception as exc:
                logger.warning("2ememain_groq_vision_api_error: %s", repr(exc))
                return TwoememainSearchResponse(
                    query=q,
                    total_items=0,
                    items=[],
                    tool_used="escalation_error",
                    blocked=True,
                    ts=datetime.now(timezone.utc).isoformat(),
                )

        items = []
        for raw in raw_items:
            price_data = raw.get("price")
            if isinstance(price_data, dict):
                price = EbayPrice(
                    value=price_data.get("value"),
                    currency=price_data.get("currency"),
                )
            else:
                price = None
            items.append(TwoememainItem(
                title=raw.get("title"),
                price=price,
                start_date=raw.get("start_date"),
                end_date=raw.get("end_date"),
                photo_url=raw.get("photo_url"),
                link=raw.get("link"),
                location=raw.get("location"),
            ))

        return TwoememainSearchResponse(
            query=q,
            total_items=len(items),
            items=items,
            tool_used=tool_used,
            blocked=blocked,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("2ememain_unhandled_error: %s", repr(exc), exc_info=True)
        return TwoememainSearchResponse(
            query=q,
            total_items=0,
            items=[],
            tool_used="escalation_error",
            blocked=True,
            error=str(exc),
            ts=datetime.now(timezone.utc).isoformat(),
        )


# --- Vinted search endpoint ---------------------------------------------------


@app.get("/vinted/search", response_model=VintedSearchResponse, tags=["vinted"])
async def vinted_search(
    q: str,
    marketplace: str = "FR",
    max_pages: int = 3,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> VintedSearchResponse:
    """Synchronous Vinted search via Scrapy spider + Universal Extractor. Auth Bearer required."""
    import asyncio
    from datetime import datetime, timezone
    from .workers import _run_scrapy_subprocess

    job_id = uuid.uuid4().hex[:16]
    url = f"https://www.vinted.fr/catalog?search_text={q}&order=newest_first"
    config = {
        "spider": "vinted",
        "q": q,
        "marketplace": marketplace,
        "max_pages": max_pages,
        "respect_robots": False,
        "groq_api_key": getattr(settings, "groq_api_key", ""),
    }

    try:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_scrapy_subprocess, job_id, url, config),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Vinted search timed out after 120s")

        raw_items = result.get("items", [])
        blocked = result.get("_meta", {}).get("blocked", False)
        tool_used = "scrapy"

        if blocked:
            return VintedSearchResponse(
                query=q,
                marketplace=marketplace,
                total_items=0,
                items=[],
                blocked=True,
                tool_used="escalation_error",
                ts=datetime.now(timezone.utc).isoformat(),
            )

        items = []
        for raw in raw_items:
            price_eur = raw.get("price_eur")
            price = EbayPrice(value=price_eur, currency="EUR") if price_eur else None
            items.append(AggregatedItem(
                title=raw.get("title"),
                price=price,
                epid=None,
                start_date=None,
                end_date=None,
                photo_url=raw.get("photo_url"),
                link=raw.get("url"),
                source="vinted",
            ))

        return VintedSearchResponse(
            query=q,
            marketplace=marketplace,
            total_items=len(items),
            items=items,
            blocked=False,
            tool_used=tool_used,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("vinted_unhandled_error: %s", repr(exc), exc_info=True)
        return VintedSearchResponse(
            query=q,
            marketplace=marketplace,
            total_items=0,
            items=[],
            blocked=True,
            tool_used="escalation_error",
            ts=datetime.now(timezone.utc).isoformat(),
        )


# --- Multi-source aggregator endpoint -----------------------------------------


@app.get("/aggregate/search", response_model=AggregateSearchResponse, tags=["aggregate"])
async def aggregate_search(
    q: str,
    marketplace: str = "EBAY_FR",
    max_pages: int = 3,
    ingest: bool = False,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> AggregateSearchResponse:
    """Parallel eBay + 2ememain search with fuzzy deduplication.

    Runs both sources concurrently; removes 2ememain items whose title ≥ 82%
    similar AND price within 25% of an eBay item. Returns a unified CSV-
    compatible list with a `source` column.
    """
    import asyncio
    from datetime import datetime, timezone

    from .aggregator import deduplicate, fetch_2ememain_raw, fetch_ebay_raw

    ebay_result, deux_result = await asyncio.gather(
        fetch_ebay_raw(q, marketplace, max_pages, settings),
        fetch_2ememain_raw(q, max_pages),
        return_exceptions=False,
    )

    # --- normalise eBay raw items ---
    ebay_items_raw = ebay_result.get("items", [])
    ebay_items = []
    for raw in ebay_items_raw:
        price_data = raw.get("price")
        price = EbayPrice(**price_data) if isinstance(price_data, dict) else None
        ebay_items.append(EbayItem(
            title=raw.get("title"),
            price=price,
            epid=raw.get("epid"),
            start_date=raw.get("start_date"),
            end_date=raw.get("end_date"),
            photo_url=raw.get("photo_url"),
            link=raw.get("link"),
        ))

    # --- normalise 2ememain raw items ---
    deux_items_raw = deux_result.get("items", [])
    twoememain_blocked = deux_result.get("_meta", {}).get("blocked", False)
    deux_items = []
    for raw in deux_items_raw:
        price_data = raw.get("price")
        price = EbayPrice(**price_data) if isinstance(price_data, dict) else None
        deux_items.append(TwoememainItem(
            title=raw.get("title"),
            price=price,
            start_date=raw.get("start_date"),
            end_date=raw.get("end_date"),
            photo_url=raw.get("photo_url"),
            link=raw.get("link"),
            location=raw.get("location"),
        ))

    merged, n_dups = deduplicate(ebay_items, deux_items)

    sources = {
        "ebay": sum(1 for i in merged if i.source == "ebay"),
        "2ememain": sum(1 for i in merged if i.source == "2ememain"),
    }

    if ingest and merged:
        from tools.stats.epid_calculator import recompute_all_stats as _recompute_agg
        _conn_agg = sqlite3.connect(str(_RISK_DB_PATH))
        try:
            from datetime import datetime as _dt2, timezone as _tz2
            _now2 = _dt2.now(_tz2.utc).isoformat()
            for it in merged:
                _url2 = it.link
                if not _url2:
                    continue
                _epid2 = getattr(it, "epid", None)
                _conn_agg.execute(
                    """
                    INSERT OR IGNORE INTO scraped_items
                        (epid, title, price_value, price_currency,
                         start_date, end_date, source, url, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _epid2, it.title,
                        it.price.value if it.price else None,
                        it.price.currency if it.price else None,
                        it.start_date, it.end_date,
                        it.source, _url2, _now2,
                    ),
                )
            _conn_agg.commit()
            _recompute_agg(_conn_agg)
        finally:
            _conn_agg.close()

    return AggregateSearchResponse(
        query=q,
        marketplace=marketplace,
        total_items=len(merged),
        items=merged,
        sources=sources,
        duplicates_removed=n_dups,
        ebay_blocked=not bool(getattr(settings, "ebay_app_ids", [])),
        twoememain_blocked=twoememain_blocked,
        ts=datetime.now(timezone.utc).isoformat(),
    )


# --- ePID stats endpoints ----------------------------------------------------


def _get_epid_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(_RISK_DB_PATH))


@app.get("/epid/stats/{epid}", response_model=EpidStats, tags=["epid"])
async def get_epid_stats(
    epid: str,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> EpidStats:
    """Return the full ePID stats sheet."""
    conn = _get_epid_conn()
    try:
        cur = conn.execute(
            """
            SELECT epid, brand, model, total_items, currency,
                   median_price, q1_price, q2_price, q3_price, q4_price,
                   avg_sell_days, min_sell_days, max_sell_days, sell_days_sample,
                   last_updated
            FROM epid_stats WHERE epid = ?
            """,
            (epid,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"ePID {epid!r} not found")

    return EpidStats(
        epid=row[0], brand=row[1], model=row[2], total_items=row[3],
        currency=row[4], median_price=row[5], q1_price=row[6], q2_price=row[7],
        q3_price=row[8], q4_price=row[9], avg_sell_days=row[10],
        min_sell_days=row[11], max_sell_days=row[12], sell_days_sample=row[13],
        last_updated=row[14],
    )


@app.post("/epid/ingest", response_model=IngestResponse, tags=["epid"])
async def ingest_epid_items(
    req: IngestRequest,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> IngestResponse:
    """Ingest scraped items into scraped_items and recompute ePID stats."""
    from datetime import datetime, timezone
    from tools.stats.epid_calculator import recompute_all_stats

    now = datetime.now(timezone.utc).isoformat()
    ingested = 0
    touched_epids: set[str] = set()

    conn = _get_epid_conn()
    try:
        for item in req.items:
            url = item.get("url")
            if not url:
                continue
            epid = item.get("epid")
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO scraped_items
                    (epid, title, price_value, price_currency,
                     start_date, end_date, source, url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    epid,
                    item.get("title"),
                    item.get("price_value"),
                    item.get("price_currency"),
                    item.get("start_date"),
                    item.get("end_date"),
                    item.get("source", req.source),
                    url,
                    now,
                ),
            )
            if cur.rowcount > 0:
                ingested += 1
                if epid:
                    touched_epids.add(epid)
        conn.commit()
        updated_epids = recompute_all_stats(conn)
    finally:
        conn.close()

    return IngestResponse(ingested=ingested, epids_updated=len(updated_epids))


@app.get("/epid/search", response_model=list[EpidStats], tags=["epid"])
async def search_epid(
    q: str,
    _token: Annotated[str, Depends(require_bearer)] = ...,
) -> list[EpidStats]:
    """Search ePID stats by brand or model (LIKE search)."""
    pattern = f"%{q}%"
    conn = _get_epid_conn()
    try:
        cur = conn.execute(
            """
            SELECT epid, brand, model, total_items, currency,
                   median_price, q1_price, q2_price, q3_price, q4_price,
                   avg_sell_days, min_sell_days, max_sell_days, sell_days_sample,
                   last_updated
            FROM epid_stats
            WHERE brand LIKE ? OR model LIKE ?
            ORDER BY total_items DESC
            LIMIT 50
            """,
            (pattern, pattern),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        EpidStats(
            epid=r[0], brand=r[1], model=r[2], total_items=r[3],
            currency=r[4], median_price=r[5], q1_price=r[6], q2_price=r[7],
            q3_price=r[8], q4_price=r[9], avg_sell_days=r[10],
            min_sell_days=r[11], max_sell_days=r[12], sell_days_sample=r[13],
            last_updated=r[14],
        )
        for r in rows
    ]
