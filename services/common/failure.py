from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from common.metrics import ServiceMetrics

logger = logging.getLogger("failure")

SKIP_PATHS = {"/metrics", "/health", "/ready", "/inject", "/inject/reset"}


@dataclass
class InjectionState:
    active: bool = False
    mode: str = "http_500"
    rate: float = 0.0
    duration: float = 0.0
    latency_ms: int = 0
    started_at: Optional[float] = None
    expires_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        remaining = None
        if self.active and self.expires_at is not None:
            remaining = max(0.0, self.expires_at - time.time())
        data["remaining_seconds"] = remaining
        return data


class FailureInjector:
    def __init__(self, metrics: ServiceMetrics) -> None:
        self.metrics = metrics
        self.state = InjectionState()
        self._reset_task: Optional[asyncio.Task[None]] = None

    def current(self) -> InjectionState:
        if (
            self.state.active
            and self.state.expires_at is not None
            and time.time() >= self.state.expires_at
        ):
            self.reset()
        return self.state

    def activate(
        self,
        mode: str = "http_500",
        rate: float = 0.8,
        duration: float = 60.0,
        latency_ms: int = 1500,
    ) -> InjectionState:
        allowed = {"http_500", "latency", "connection", "dependency"}
        if mode not in allowed:
            raise ValueError(f"Unsupported failure mode: {mode}")
        self.reset()
        now = time.time()
        self.state = InjectionState(
            active=True,
            mode=mode,
            rate=max(0.0, min(1.0, rate)),
            duration=duration,
            latency_ms=max(0, latency_ms),
            started_at=now,
            expires_at=now + duration if duration > 0 else None,
        )
        self.metrics.set_injection(mode, True)
        self.metrics.set_health(0.0 if rate >= 0.5 else 0.5)
        logger.warning(
            "failure injection activated",
            extra={"service": self.metrics.service_name},
        )
        try:
            loop = asyncio.get_running_loop()
            if duration > 0:
                self._reset_task = loop.create_task(self._auto_reset(duration))
        except RuntimeError:
            pass
        return self.state

    def reset(self) -> InjectionState:
        if self._reset_task and not self._reset_task.done():
            self._reset_task.cancel()
        previous = self.state.mode
        self.state = InjectionState()
        self.metrics.set_injection(previous, False)
        self.metrics.set_health(1.0)
        return self.state

    async def _auto_reset(self, duration: float) -> None:
        try:
            await asyncio.sleep(duration)
            self.reset()
            logger.info("failure injection expired")
        except asyncio.CancelledError:
            return

    async def maybe_apply(self, path: str) -> Optional[Response]:
        state = self.current()
        if not state.active or path in SKIP_PATHS:
            return None

        if state.mode == "latency" or (
            state.mode == "http_500" and state.latency_ms > 0
        ):
            if random.random() < (state.rate if state.mode == "latency" else 1.0):
                await asyncio.sleep(state.latency_ms / 1000.0)

        if state.mode in {"http_500", "connection"} and random.random() < state.rate:
            if state.mode == "connection":
                return JSONResponse(
                    {"error": "injected connection failure", "injected": True},
                    status_code=503,
                )
            return JSONResponse(
                {"error": "injected synthetic failure", "injected": True},
                status_code=500,
            )

        if state.mode == "dependency" and random.random() < state.rate:
            return JSONResponse(
                {"error": "injected dependency failure", "injected": True},
                status_code=502,
            )
        return None

    def should_fail_dependency(self) -> bool:
        state = self.current()
        return (
            state.active
            and state.mode == "dependency"
            and random.random() < state.rate
        )


class FailureMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, injector: FailureInjector) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.injector = injector

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        injected = await self.injector.maybe_apply(request.url.path)
        if injected is not None:
            return injected
        return await call_next(request)


def register_inject_routes(app: FastAPI, injector: FailureInjector) -> None:
    @app.post("/inject")
    async def inject(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        state = injector.activate(
            mode=str(body.get("mode", "http_500")),
            rate=float(body.get("rate", 0.8)),
            duration=float(body.get("duration", 60)),
            latency_ms=int(body.get("latency_ms", 1500)),
        )
        return {"ok": True, "injection": state.to_dict()}

    @app.get("/inject")
    async def inject_status() -> dict[str, Any]:
        return {"ok": True, "injection": injector.current().to_dict()}

    @app.post("/inject/reset")
    async def inject_reset() -> dict[str, Any]:
        return {"ok": True, "injection": injector.reset().to_dict()}
