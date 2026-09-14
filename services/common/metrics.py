from __future__ import annotations

import re
import time
from typing import Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

ID_RE = re.compile(r"/[0-9a-fA-F-]{8,}")
NUMERIC_RE = re.compile(r"/\d+")

LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


class ServiceMetrics:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.registry = CollectorRegistry()
        self.requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["service", "endpoint", "method", "status_code"],
            registry=self.registry,
        )
        self.errors_total = Counter(
            "http_request_errors_total",
            "Total failed HTTP requests",
            ["service", "endpoint", "method", "status_code"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["service", "endpoint", "method"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.health = Gauge(
            "service_health",
            "Service health: 1 healthy, 0.5 degraded, 0 down",
            ["service"],
            registry=self.registry,
        )
        self.injection_active = Gauge(
            "failure_injection_active",
            "Whether synthetic failure injection is currently active",
            ["service", "mode"],
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "http_requests_in_flight",
            "In-flight HTTP requests",
            ["service"],
            registry=self.registry,
        )
        self.health.labels(service=service_name).set(1)
        self.injection_active.labels(service=service_name, mode="none").set(0)
        self.in_flight.labels(service=service_name).set(0)

    def observe_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        status = str(status_code)
        labels = {
            "service": self.service_name,
            "endpoint": endpoint,
            "method": method,
            "status_code": status,
        }
        self.requests_total.labels(**labels).inc()
        self.duration.labels(
            service=self.service_name,
            endpoint=endpoint,
            method=method,
        ).observe(duration_seconds)
        if status_code >= 400:
            self.errors_total.labels(**labels).inc()

    def set_health(self, value: float) -> None:
        self.health.labels(service=self.service_name).set(value)

    def set_injection(self, mode: str, active: bool) -> None:
        self.injection_active.labels(service=self.service_name, mode=mode).set(
            1 if active else 0
        )
        if not active:
            self.injection_active.labels(service=self.service_name, mode="none").set(0)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def normalize_endpoint(path: str) -> str:
    path = NUMERIC_RE.sub("/:id", path)
    path = ID_RE.sub("/:id", path)
    if len(path) > 64:
        path = path[:64]
    return path or "/"


class MetricsMiddleware(BaseHTTPMiddleware):
    SKIP = {"/metrics", "/health", "/ready"}

    def __init__(self, app, metrics: ServiceMetrics) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in self.SKIP:
            return await call_next(request)

        endpoint = normalize_endpoint(path)
        method = request.method
        self.metrics.in_flight.labels(service=self.metrics.service_name).inc()
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            duration = time.perf_counter() - start
            self.metrics.in_flight.labels(service=self.metrics.service_name).dec()
            self.metrics.observe_request(endpoint, method, status_code, duration)


def metrics_response(metrics: ServiceMetrics) -> Response:
    return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)
