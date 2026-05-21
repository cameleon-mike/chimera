"""FastAPI bridge — entrypoint for cameleon.

Step 1.2: skeletons of all 6 endpoints, auth wired, structured logging.
Step 1.3 will replace the stubs with real RQ enqueue / status / result.
Step 2.3 will implement /risk/{domain}.
Step 3.2 will implement /download/{job_id}.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request

from . import __version__, manifest as mf
from .auth import require_bearer
from .config import get_settings
from .logging_setup import setup_logging, write_audit
from . import queue as q
from .schemas import (
    HealthResponse,
    JobStatus,
    ResultResponse,
    RiskResponse,
    RunToolRequest,
    RunToolResponse,
    StatusResponse,
)

logger = setup_logging()
settings = get_settings()

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
    _token: Annotated[str, Depends(require_bearer)],
) -> RiskResponse:
    """Aggregated risk history for a domain. Stub — real implementation Step 2.3."""
    return RiskResponse(
        domain=domain,
        last_24h={},
        recommendation="not implemented yet (lands in Step 2.3)",
    )


@app.get("/download/{job_id}", tags=["jobs"])
async def download_artifact(
    job_id: str,
    _token: Annotated[str, Depends(require_bearer)],
):
    """Binary download (PNG) for screenshot jobs. Lands in Step 3.2."""
    raise HTTPException(status_code=501, detail="not implemented yet (lands in Step 3.2)")
