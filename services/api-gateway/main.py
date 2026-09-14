from __future__ import annotations

import os
import random
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from common.app import create_service
from common.failure import FailureInjector
from common.http import call_service

SERVICE_NAME = "api-gateway"
USER_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001")
PAYMENT_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8002")
NOTIFY_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8003")

USERS = ["u-1001", "u-1002", "u-1003"]


def register_routes(app: FastAPI, injector: FailureInjector) -> None:
    client = httpx.AsyncClient()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await client.aclose()

    @app.get("/api/users")
    async def users() -> Any:
        status, body = await call_service(client, "GET", f"{USER_URL}/users")
        return JSONResponse(body, status_code=status)

    @app.get("/api/users/{user_id}")
    async def user(user_id: str) -> Any:
        status, body = await call_service(client, "GET", f"{USER_URL}/users/{user_id}")
        return JSONResponse(body, status_code=status)

    @app.get("/api/users/{user_id}/billing")
    async def billing(user_id: str) -> Any:
        if injector.should_fail_dependency():
            return JSONResponse(
                {"error": "injected dependency failure", "injected": True},
                status_code=502,
            )
        status, body = await call_service(
            client, "GET", f"{USER_URL}/users/{user_id}/billing"
        )
        return JSONResponse(body, status_code=status)

    @app.post("/api/checkout")
    async def checkout(payload: dict[str, Any] | None = None) -> Any:
        body = payload or {}
        user_id = body.get("user_id") or random.choice(USERS)
        amount = float(body.get("amount", round(random.uniform(9.99, 89.99), 2)))

        if injector.should_fail_dependency():
            return JSONResponse(
                {"error": "injected dependency failure", "injected": True},
                status_code=502,
            )

        user_status, user_body = await call_service(
            client, "POST", f"{USER_URL}/users/{user_id}/validate"
        )
        if user_status >= 400:
            return JSONResponse(
                {"stage": "user-service", "upstream": user_body},
                status_code=user_status,
            )

        pay_status, pay_body = await call_service(
            client,
            "POST",
            f"{PAYMENT_URL}/payments",
            json={"user_id": user_id, "amount": amount},
        )
        if pay_status >= 400:
            return JSONResponse(
                {"stage": "payment-service", "upstream": pay_body},
                status_code=pay_status,
            )

        ntf_status, ntf_body = await call_service(
            client,
            "POST",
            f"{NOTIFY_URL}/notify",
            json={
                "user_id": user_id,
                "template": "payment_receipt",
                "channel": "email",
            },
        )
        overall = 200 if ntf_status < 400 else ntf_status
        return JSONResponse(
            {
                "ok": overall < 400,
                "user": user_body,
                "payment": pay_body,
                "notification": ntf_body,
            },
            status_code=overall,
        )

    @app.get("/api/payments")
    async def payments() -> Any:
        status, body = await call_service(client, "GET", f"{PAYMENT_URL}/payments")
        return JSONResponse(body, status_code=status)

    @app.post("/api/notify")
    async def notify(payload: dict[str, Any] | None = None) -> Any:
        status, body = await call_service(
            client, "POST", f"{NOTIFY_URL}/notify", json=payload or {}
        )
        return JSONResponse(body, status_code=status)


app = create_service(
    SERVICE_NAME,
    "Edge API gateway for the demo microservice cluster",
    register_routes,
)
