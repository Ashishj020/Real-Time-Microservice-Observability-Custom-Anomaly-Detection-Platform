from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger("slack")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_incident_message(
    incident: dict[str, Any],
    dashboard_url: str,
    recovered: bool = False,
) -> dict[str, Any]:
    service = incident.get("service", "unknown")
    incident_id = incident.get("id", "n/a")
    severity = str(incident.get("severity", "high")).upper()
    detected = incident.get("detected_at") or incident.get("timestamp")
    if isinstance(detected, datetime):
        detected = detected.strftime("%H:%M:%S")
    mttd = incident.get("mttd_seconds")
    mttd_line = f"*MTTD:* {mttd:.2f}s" if isinstance(mttd, (int, float)) else "*MTTD:* pending"

    if recovered:
        header = "✅ SERVICE RECOVERED"
        color = "#3dd68c"
        title = f"{service} returned to baseline"
    else:
        header = f"🚨 {severity} INCIDENT"
        color = "#ff4d6d" if severity == "CRITICAL" else "#f5c542"
        title = f"{service} — Error Rate Spike"

    text = (
        f"{header}\n\n"
        f"*{title}*\n"
        f"Current Error Rate: {_pct(float(incident.get('value', 0)))}\n"
        f"Baseline: {_pct(float(incident.get('baseline', 0)))}\n"
        f"Z-Score: {incident.get('z_score', 0)}\n"
        f"Detected: {detected}\n"
        f"Incident ID: {incident_id}\n"
        f"{mttd_line}\n"
        f"<{dashboard_url}|Open Observability Dashboard →>"
    )
    return {
        "text": text,
        "attachments": [
            {
                "color": color,
                "mrkdwn_in": ["text"],
                "text": text,
            }
        ],
    }


class SlackAlerter:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url.strip()
        self._client = httpx.AsyncClient(timeout=8.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def send_incident(
        self,
        incident: dict[str, Any],
        dashboard_url: str,
        recovered: bool = False,
    ) -> dict[str, Any]:
        payload = build_incident_message(incident, dashboard_url, recovered=recovered)
        if not self.webhook_url:
            logger.info("slack webhook not configured; skipping alert for %s", incident.get("id"))
            return {"sent": False, "reason": "webhook_not_configured"}
        try:
            response = await self._client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.info("slack alert sent for %s", incident.get("id"))
            return {"sent": True, "status_code": response.status_code}
        except Exception as exc:
            logger.warning("slack alert failed: %s", exc)
            return {"sent": False, "reason": str(exc)}
