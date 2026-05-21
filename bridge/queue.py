"""Thin wrapper around RQ for the Chimera bridge.

Three queues by priority (`high`, `normal`, `low`). Each enqueued job becomes
a row in Redis under the key `rq:job:<job_id>` — the bridge's job_id IS the
RQ job_id (no separate mapping table).

Step 1.3 wires this up with stub workers (in `bridge.workers`); real runners
land in Step 1.4 (scrapy), Step 3.2 (screenshot), etc.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.job import JobStatus as RQJobStatus

from .config import get_settings
from .schemas import JobStatus, Priority

WORKER_FN = "bridge.workers.dispatch_job"


@lru_cache(maxsize=1)
def _redis_conn() -> redis.Redis:
    return redis.from_url(get_settings().redis_url)


@lru_cache(maxsize=1)
def _queues() -> dict[Priority, Queue]:
    conn = _redis_conn()
    return {
        Priority.high: Queue("high", connection=conn),
        Priority.normal: Queue("normal", connection=conn),
        Priority.low: Queue("low", connection=conn),
    }


def queue_names() -> list[str]:
    """Order matches RQ worker priority: high first."""
    return ["high", "normal", "low"]


def enqueue_job(
    job_id: str,
    tool: str,
    url: str | list[str],
    config: dict[str, Any],
    priority: Priority,
    callback_url: str | None = None,
) -> Job:
    """Submit a job to the correct queue. Returns the RQ Job (job.id == our job_id)."""
    queue = _queues()[priority]
    return queue.enqueue(
        WORKER_FN,
        args=(job_id, tool, url, config),
        kwargs={"callback_url": callback_url},
        job_id=job_id,
        job_timeout=get_settings().rq_default_timeout,
        result_ttl=86400,           # keep result in Redis for 24 h
        failure_ttl=86400,
    )


def fetch_job(job_id: str) -> Job | None:
    """Return the RQ Job or None if job_id is unknown.

    Only NoSuchJobError yields None. Redis connectivity errors (ConnectionError,
    TimeoutError, etc.) propagate up so the caller sees a real failure instead
    of a misleading not_found. Resolves TD-1.
    """
    try:
        return Job.fetch(job_id, connection=_redis_conn())
    except NoSuchJobError:
        return None


# RQ → bridge status mapping --------------------------------------------------

_RQ_TO_BRIDGE = {
    RQJobStatus.QUEUED:    JobStatus.queued,
    RQJobStatus.DEFERRED:  JobStatus.queued,
    RQJobStatus.SCHEDULED: JobStatus.queued,
    RQJobStatus.STARTED:   JobStatus.started,
    RQJobStatus.FINISHED:  JobStatus.finished,
    RQJobStatus.FAILED:    JobStatus.failed,
    RQJobStatus.STOPPED:   JobStatus.failed,
    RQJobStatus.CANCELED:  JobStatus.failed,
}


def map_status(rq_status: RQJobStatus | str | None) -> JobStatus:
    if rq_status is None:
        return JobStatus.not_found
    if isinstance(rq_status, str):
        try:
            rq_status = RQJobStatus(rq_status)
        except ValueError:
            return JobStatus.not_found
    return _RQ_TO_BRIDGE.get(rq_status, JobStatus.not_found)


# Result persistence ----------------------------------------------------------


def result_path(job_id: str):
    return get_settings().results_dir / f"{job_id}.json"


def save_result(job_id: str, result: dict[str, Any]) -> None:
    settings = get_settings()
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    path = result_path(job_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def load_result(job_id: str) -> dict[str, Any] | None:
    path = result_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
