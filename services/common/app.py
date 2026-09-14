from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.failure import FailureInjector, FailureMiddleware, register_inject_routes
from common.logging_config import configure_logging
from common.metrics import MetricsMiddleware, ServiceMetrics, metrics_response


def create_service(
    service_name: str,
    description: str,
    register_routes: Callable[[FastAPI, FailureInjector], None],
) -> FastAPI:
    configure_logging(service_name)
    metrics = ServiceMetrics(service_name)
    injector = FailureInjector(metrics)

    app = FastAPI(title=service_name, description=description, version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(FailureMiddleware, injector=injector)
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    app.state.metrics = metrics
    app.state.injector = injector
    app.state.service_name = service_name

    @app.get("/health")
    async def health() -> dict[str, Any]:
        state = injector.current()
        status = "healthy"
        if state.active:
            status = "critical" if state.rate >= 0.5 else "degraded"
        return {
            "service": service_name,
            "status": status,
            "injection": state.to_dict(),
        }

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/metrics")
    async def prometheus_metrics() -> Any:
        return metrics_response(metrics)

    register_inject_routes(app, injector)
    register_routes(app, injector)
    return app
