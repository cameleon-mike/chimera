"""Prometheus instrumentation middleware."""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from bridge import metrics


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request count + duration for every request, labelled by route."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None) or request.url.path
        metrics.requests_total.labels(
            endpoint=endpoint, status_code=str(response.status_code)
        ).inc()
        metrics.request_duration_seconds.labels(endpoint=endpoint).observe(duration)
        return response
