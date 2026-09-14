from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import httpx

from alerting import SlackAlerter
from config import settings
from detector.rolling_zscore import Observation, RollingZScoreDetector, utcnow
from prom import PrometheusClient
from store import IncidentStore
from ws_hub import Hub

logger = logging.getLogger("engine")

SERVICES = settings.service_names()
SERVICE_URLS = {
    "api-gateway": os.getenv("API_GATEWAY_URL", "http://api-gateway:8000"),
    "user-service": os.getenv("USER_SERVICE_URL", "http://user-service:8001"),
    "payment-service": os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8002"),
    "notification-service": os.getenv(
        "NOTIFICATION_SERVICE_URL", "http://notification-service:8003"
    ),
}
TOPOLOGY = {
    "nodes": [
        {"id": "api-gateway", "label": "API Gateway", "tier": 0},
        {"id": "user-service", "label": "User Service", "tier": 1},
        {"id": "payment-service", "label": "Payment Service", "tier": 1},
        {"id": "notification-service", "label": "Notification Service", "tier": 1},
    ],
    "edges": [
        {"from": "api-gateway", "to": "user-service"},
        {"from": "api-gateway", "to": "payment-service"},
        {"from": "api-gateway", "to": "notification-service"},
        {"from": "user-service", "to": "payment-service"},
    ],
}


def health_label(sample: dict[str, Any], in_incident: bool) -> str:
    if in_incident or sample.get("error_rate", 0) >= 0.25:
        return "critical"
    if sample.get("injection_active") or sample.get("error_rate", 0) >= 0.08:
        return "degraded"
    if sample.get("health_value", 1) <= 0:
        return "critical"
    if sample.get("health_value", 1) < 1:
        return "degraded"
    return "healthy"


class Engine:
    def __init__(self) -> None:
        self.prom = PrometheusClient(settings.prometheus_url)
        self.slack = SlackAlerter(settings.slack_webhook_url)
        self.store = IncidentStore()
        self.hub = Hub()
        self.detectors = {
            name: RollingZScoreDetector(
                window=settings.anomaly_window,
                z_threshold=settings.z_score_threshold,
                min_request_count=settings.min_request_count,
                consecutive_breaches=settings.consecutive_breaches,
                alert_cooldown=settings.alert_cooldown,
                recovery_observations=settings.recovery_observations,
                warmup_samples=settings.warmup_samples,
            )
            for name in SERVICES
        }
        self.task: Optional[asyncio.Task[None]] = None
        self.config_profile = "baseline"

    def detector_config(self) -> dict[str, Any]:
        first = next(iter(self.detectors.values()))
        return {
            "profile": self.config_profile,
            **first.snapshot(),
            "sample_interval": settings.sample_interval,
            "query_window": settings.query_window,
        }

    async def loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("engine tick failed")
            await asyncio.sleep(settings.sample_interval)

    async def tick(self) -> None:
        now = utcnow()
        samples: dict[str, dict[str, Any]] = {}
        raw_all = await self.prom.collect_all(
            SERVICES, settings.query_window, settings.rate_window
        )
        for name in SERVICES:
            raw = raw_all.get(name) or {
                "service": name,
                "error_rate": 0.0,
                "request_count": 0.0,
                "request_rate": 0.0,
                "p95_latency": 0.0,
                "success_count": 0.0,
                "error_count": 0.0,
                "health_value": 1.0,
                "injection_active": False,
            }
            detector = self.detectors[name]
            observation = Observation(
                timestamp=now,
                error_rate=raw["error_rate"],
                request_count=raw["request_count"],
                request_rate=raw["request_rate"],
                p95_latency=raw["p95_latency"],
                success_count=raw["success_count"],
                error_count=raw["error_count"],
                health_value=raw["health_value"],
                injection_active=raw["injection_active"],
            )
            result = detector.observe(observation)
            health = health_label(raw, detector.in_incident)
            sample = {
                **raw,
                "timestamp": now.isoformat(),
                "z_score": result.z_score,
                "baseline": result.baseline,
                "sigma": result.sigma,
                "health": health,
                "in_incident": detector.in_incident,
                "breach_streak": result.consecutive,
            }
            samples[name] = sample
            self.store.record_metrics(sample)

            if result.triggered:
                incident = self.store.open_incident(
                    service=name,
                    value=result.value,
                    baseline=result.baseline,
                    z_score=result.z_score,
                    severity=result.severity,
                    reason=result.reason,
                )
                slack_result = await self.slack.send_incident(
                    incident.to_dict(), settings.dashboard_url, recovered=False
                )
                self.store.mark_alerted(incident, slack_result)
                await self.hub.broadcast(
                    {
                        "type": "incident",
                        "payload": incident.to_dict(),
                        "mttd": self.store.mttd_summary(),
                    }
                )
            elif result.recovered:
                incident = self.store.recover(name, result.value, result.baseline)
                if incident:
                    await self.slack.send_incident(
                        incident.to_dict(), settings.dashboard_url, recovered=True
                    )
                    await self.hub.broadcast(
                        {"type": "recovery", "payload": incident.to_dict()}
                    )

        await self.hub.broadcast(
            {
                "type": "metrics",
                "payload": {
                    "services": samples,
                    "mttd": self.store.mttd_summary(),
                    "timestamp": now.isoformat(),
                    "config": self.detector_config(),
                },
            }
        )

    async def apply_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        kwargs = {}
        mapping = {
            "anomaly_window": "window",
            "window": "window",
            "z_score_threshold": "z_threshold",
            "z_threshold": "z_threshold",
            "min_request_count": "min_request_count",
            "consecutive_breaches": "consecutive_breaches",
            "alert_cooldown": "alert_cooldown",
            "recovery_observations": "recovery_observations",
            "warmup_samples": "warmup_samples",
        }
        for src, dest in mapping.items():
            if src in payload:
                kwargs[dest] = type(getattr(next(iter(self.detectors.values())), dest))(
                    payload[src]
                )
        if "profile" in payload:
            self.config_profile = str(payload["profile"])
        for detector in self.detectors.values():
            detector.configure(**kwargs)
            detector.in_incident = False
            detector.breach_streak = 0
            detector.recovery_streak = 0
            detector.last_alert_at = None
        return self.detector_config()


engine = Engine()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    engine.task = asyncio.create_task(engine.loop())
    logger.info("anomaly engine started for %s", SERVICES)
    yield
    if engine.task:
        engine.task.cancel()
    await engine.prom.close()
    await engine.slack.close()


app = FastAPI(title="Anomaly Detection Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/snapshot")
async def snapshot() -> dict[str, Any]:
    data = engine.store.snapshot()
    data["topology"] = TOPOLOGY
    data["config"] = engine.detector_config()
    return data


@app.get("/api/services")
async def services() -> dict[str, Any]:
    return {"services": engine.store.latest_metrics}


@app.get("/api/incidents")
async def incidents() -> dict[str, Any]:
    return {"incidents": [i.to_dict() for i in engine.store.incidents.values()][::-1]}


@app.get("/api/incidents/{incident_id}")
async def incident_detail(incident_id: str) -> dict[str, Any]:
    incident = engine.store.incidents.get(incident_id)
    if not incident:
        return {"error": "not_found"}
    return incident.to_dict()


@app.get("/api/mttd")
async def mttd() -> dict[str, Any]:
    return engine.store.mttd_summary()


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return engine.detector_config()


@app.post("/api/config")
async def set_config(payload: dict[str, Any]) -> dict[str, Any]:
    return await engine.apply_config(payload)


@app.post("/api/inject")
async def inject_failure(payload: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "payment": "payment-service",
        "user": "user-service",
        "gateway": "api-gateway",
        "notification": "notification-service",
        "notify": "notification-service",
    }
    service = aliases.get(str(payload.get("service", "payment-service")), str(payload.get("service", "payment-service")))
    recover = bool(payload.get("recover") or payload.get("mode") == "reset")
    target = SERVICE_URLS.get(service)
    if not target:
        return {"ok": False, "error": f"unknown service {service}"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        if recover:
            resp = await client.post(f"{target}/inject/reset")
        else:
            body = {
                "mode": payload.get("mode", "http_500"),
                "rate": float(payload.get("rate", 0.8)),
                "duration": float(payload.get("duration", 45)),
                "latency_ms": int(payload.get("latency_ms", 0)),
            }
            resp = await client.post(f"{target}/inject", json=body)
        try:
            service_body = resp.json()
        except Exception:
            service_body = {"raw": resp.text}
    event = engine.store.note_injection(service, payload if not recover else {"mode": "reset"})
    await engine.hub.broadcast(
        {
            "type": "injection",
            "payload": {
                "service": service,
                "params": payload,
                "timestamp": event["timestamp"],
                "recover": recover,
            },
            "mttd": engine.store.mttd_summary(),
        }
    )
    return {"ok": True, "service": service, "service_response": service_body, "event": event}


@app.post("/api/injection")
async def injection(payload: dict[str, Any]) -> dict[str, Any]:
    service = str(payload.get("service", "payment-service"))
    aliases = {
        "payment": "payment-service",
        "user": "user-service",
        "gateway": "api-gateway",
        "api-gateway": "api-gateway",
        "notification": "notification-service",
        "notify": "notification-service",
    }
    service = aliases.get(service, service)
    event = engine.store.note_injection(service, payload)
    await engine.hub.broadcast(
        {
            "type": "injection",
            "payload": {
                "service": service,
                "params": payload,
                "timestamp": event["timestamp"],
            },
            "mttd": engine.store.mttd_summary(),
        }
    )
    return {"ok": True, "event": event}


@app.post("/api/experiments")
async def record_experiment(payload: dict[str, Any]) -> dict[str, Any]:
    record = {**payload, "recorded_at": utcnow().isoformat()}
    engine.store.experiments.append(record)
    return {"ok": True, "experiment": record}


@app.get("/api/experiments")
async def experiments() -> dict[str, Any]:
    return {"experiments": engine.store.experiments}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await engine.hub.connect(ws)
    try:
        await ws.send_json({"type": "snapshot", "payload": (await snapshot())})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await engine.hub.disconnect(ws)
    except Exception:
        await engine.hub.disconnect(ws)
