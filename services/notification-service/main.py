from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI

from common.app import create_service
from common.failure import FailureInjector

SERVICE_NAME = "notification-service"

NOTIFICATIONS: list[dict[str, Any]] = []


def register_routes(app: FastAPI, injector: FailureInjector) -> None:
    @app.post("/notify")
    async def notify(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        record = {
            "id": f"ntf-{uuid.uuid4().hex[:10]}",
            "user_id": body.get("user_id", "u-1001"),
            "channel": body.get("channel", "email"),
            "template": body.get("template", "payment_receipt"),
            "status": "queued",
            "created_at": time.time(),
        }
        NOTIFICATIONS.append(record)
        if len(NOTIFICATIONS) > 200:
            del NOTIFICATIONS[:50]
        return record

    @app.get("/notify")
    async def list_notifications() -> dict[str, Any]:
        return {"notifications": NOTIFICATIONS[-25:], "count": len(NOTIFICATIONS)}


app = create_service(
    SERVICE_NAME,
    "Notification dispatch service",
    register_routes,
)
