from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

ALIASES = {
    "payment": "payment-service",
    "payment-service": "payment-service",
    "user": "user-service",
    "user-service": "user-service",
    "gateway": "api-gateway",
    "api-gateway": "api-gateway",
    "notification": "notification-service",
    "notify": "notification-service",
    "notification-service": "notification-service",
}

DEFAULT_PORTS = {
    "api-gateway": 8000,
    "user-service": 8001,
    "payment-service": 8002,
    "notification-service": 8003,
}


def service_url(name: str) -> str:
    env_key = name.upper().replace("-", "_") + "_URL"
    if os.getenv(env_key):
        return os.environ[env_key]
    host = os.getenv("SERVICE_HOST", "http://localhost")
    return f"{host}:{DEFAULT_PORTS[name]}"


def engine_url() -> str:
    return os.getenv("ANOMALY_ENGINE_URL", "http://localhost:8080")


def inject(
    service: str,
    duration: float,
    rate: float,
    mode: str,
    latency_ms: int,
    recover: bool = False,
) -> dict[str, Any]:
    name = ALIASES.get(service, service)
    if name not in DEFAULT_PORTS:
        raise SystemExit(f"Unknown service '{service}'. Choose from: {list(ALIASES)}")

    target = service_url(name)
    with httpx.Client(timeout=8.0) as client:
        if recover:
            service_resp = client.post(f"{target}/inject/reset")
            engine_resp = client.post(
                f"{engine_url()}/api/injection",
                json={"service": name, "mode": "reset", "rate": 0, "duration": 0},
            )
            return {
                "service": name,
                "action": "reset",
                "service_response": service_resp.json(),
                "engine_response": engine_resp.json(),
            }

        payload = {
            "service": name,
            "mode": mode,
            "rate": rate,
            "duration": duration,
            "latency_ms": latency_ms,
        }
        service_resp = client.post(f"{target}/inject", json=payload)
        service_resp.raise_for_status()
        try:
            engine_resp = client.post(f"{engine_url()}/api/injection", json=payload)
            engine_body = engine_resp.json()
        except Exception as exc:
            engine_body = {"ok": False, "reason": str(exc)}
        return {
            "service": name,
            "action": "inject",
            "injected_at": time.time(),
            "params": payload,
            "service_response": service_resp.json(),
            "engine_response": engine_body,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject synthetic failures into a demo microservice."
    )
    parser.add_argument(
        "--service",
        default="payment",
        help="payment | user | gateway | notification",
    )
    parser.add_argument("--duration", type=float, default=45, help="seconds")
    parser.add_argument("--rate", type=float, default=0.8, help="failure probability 0-1")
    parser.add_argument(
        "--type",
        "--mode",
        dest="mode",
        default="http_500",
        choices=["http_500", "latency", "connection", "dependency"],
    )
    parser.add_argument("--latency-ms", type=int, default=1500)
    parser.add_argument("--recover", action="store_true", help="clear injection immediately")
    args = parser.parse_args()
    result = inject(args.service, args.duration, args.rate, args.mode, args.latency_ms, args.recover)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
