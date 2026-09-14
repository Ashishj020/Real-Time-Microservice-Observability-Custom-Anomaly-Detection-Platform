from __future__ import annotations

import random
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from common.app import create_service
from common.failure import FailureInjector

SERVICE_NAME = "payment-service"

PAYMENTS: dict[str, dict[str, Any]] = {}


def register_routes(app: FastAPI, injector: FailureInjector) -> None:
    @app.post("/payments")
    async def create_payment(payload: dict[str, Any] | None = None) -> Any:
        body = payload or {}
        user_id = body.get("user_id", "u-1001")
        amount = float(body.get("amount", 24.99))
        if random.random() < 0.015:
            return JSONResponse(
                {"error": "card_declined", "retryable": True},
                status_code=402,
            )
        payment_id = f"pay-{uuid.uuid4().hex[:10]}"
        record = {
            "id": payment_id,
            "user_id": user_id,
            "amount": amount,
            "currency": body.get("currency", "USD"),
            "status": "captured",
            "created_at": time.time(),
        }
        PAYMENTS[payment_id] = record
        return record

    @app.get("/payments")
    async def list_payments() -> dict[str, Any]:
        items = list(PAYMENTS.values())[-25:]
        return {"payments": items, "count": len(PAYMENTS)}

    @app.get("/payments/user/{user_id}")
    async def payments_for_user(user_id: str) -> dict[str, Any]:
        items = [p for p in PAYMENTS.values() if p["user_id"] == user_id]
        return {
            "user_id": user_id,
            "payments": items[-10:],
            "balance_ok": True,
            "method": "visa_4242",
        }

    @app.get("/payments/{payment_id}")
    async def get_payment(payment_id: str) -> dict[str, Any]:
        payment = PAYMENTS.get(payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="payment not found")
        return payment


app = create_service(
    SERVICE_NAME,
    "Payment capture and billing service",
    register_routes,
)
