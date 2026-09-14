from __future__ import annotations

import os
import random
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from common.app import create_service
from common.failure import FailureInjector
from common.http import call_service

import httpx

SERVICE_NAME = "user-service"
PAYMENT_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8002")

USERS = {
    "u-1001": {"id": "u-1001", "name": "Ava Chen", "plan": "pro", "region": "us-east"},
    "u-1002": {"id": "u-1002", "name": "Noah Patel", "plan": "starter", "region": "eu-west"},
    "u-1003": {"id": "u-1003", "name": "Mia Rossi", "plan": "pro", "region": "ap-south"},
}


def register_routes(app: FastAPI, injector: FailureInjector) -> None:
    client = httpx.AsyncClient()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await client.aclose()

    @app.get("/users")
    async def list_users() -> dict[str, Any]:
        return {"users": list(USERS.values()), "count": len(USERS)}

    @app.get("/users/{user_id}")
    async def get_user(user_id: str) -> dict[str, Any]:
        user = USERS.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        return user

    @app.post("/users/{user_id}/validate")
    async def validate_user(user_id: str) -> dict[str, Any]:
        user = USERS.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        if random.random() < 0.01:
            return JSONResponse(
                {"valid": False, "reason": "transient_profile_error"},
                status_code=503,
            )
        return {"valid": True, "user": user}

    @app.get("/users/{user_id}/billing")
    async def user_billing(user_id: str) -> dict[str, Any]:
        user = USERS.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        if injector.should_fail_dependency():
            return JSONResponse(
                {"error": "payment dependency unavailable", "injected": True},
                status_code=502,
            )
        status, body = await call_service(
            client,
            "GET",
            f"{PAYMENT_URL}/payments/user/{user_id}",
        )
        if status >= 400:
            return JSONResponse(
                {"user": user, "billing": body, "upstream_status": status},
                status_code=status if status != 404 else 200,
            )
        return {"user": user, "billing": body}


app = create_service(
    SERVICE_NAME,
    "User profile and validation service",
    register_routes,
)
