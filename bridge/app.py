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

from . import __version__, manifest as mf
from .auth import require_bearer
from .config import get_settings
from .logging_setup import setup_logging, write_audit
from . import queue as q
from .schemas import (
    EscalateRequest,
    EscalateResponse,
    HealthResponse,
    JobStatus,
    ProbeResponse,
    ResultResponse,
    RiskResponse,
    RunToolRequest,
    RunToolResponse,
    StatusResponse,
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
        """)
        conn.commit()
    finally:
        conn.close()


_init_risk_db()

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
    return mf.load_manifest()


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
    """Binary download (PNG) for screenshot jobs. Lands in Step 3.2."""
    raise HTTPException(status_code=501, detail="not implemented yet (lands in Step 3.2)")
