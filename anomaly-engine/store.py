from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Deque, Optional

from detector.rolling_zscore import utcnow


def iso(ts: Optional[datetime]) -> Optional[str]:
    return ts.isoformat() if ts else None


@dataclass
class Incident:
    id: str
    service: str
    metric: str = "error_rate"
    status: str = "triggered"
    severity: str = "high"
    value: float = 0.0
    baseline: float = 0.0
    z_score: float = 0.0
    reason: str = ""
    injected_at: Optional[datetime] = None
    detected_at: Optional[datetime] = None
    alerted_at: Optional[datetime] = None
    recovered_at: Optional[datetime] = None
    mttd_seconds: Optional[float] = None
    slack: dict[str, Any] = field(default_factory=dict)
    injection: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["injected_at"] = iso(self.injected_at)
        data["detected_at"] = iso(self.detected_at)
        data["alerted_at"] = iso(self.alerted_at)
        data["recovered_at"] = iso(self.recovered_at)
        data["timestamp"] = iso(self.detected_at or self.injected_at or utcnow())
        return data


class IncidentStore:
    def __init__(self) -> None:
        self.incidents: dict[str, Incident] = {}
        self.open_by_service: dict[str, str] = {}
        self.counter = 0
        self.events: Deque[dict[str, Any]] = deque(maxlen=400)
        self.metric_history: dict[str, Deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=120)
        )
        self.latest_metrics: dict[str, dict[str, Any]] = {}
        self.mttd_history: list[float] = []
        self.pending_injection: dict[str, dict[str, Any]] = {}
        self.experiments: list[dict[str, Any]] = []

    def _next_id(self, when: datetime) -> str:
        self.counter += 1
        return f"INC-{when:%Y-%m%d}-{self.counter:03d}".replace(" ", "")

    def add_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("timestamp", utcnow().isoformat())
        self.events.appendleft(event)
        return event

    def record_metrics(self, sample: dict[str, Any]) -> None:
        service = sample["service"]
        self.latest_metrics[service] = sample
        self.metric_history[service].append(sample)

    def note_injection(self, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        record = {
            "service": service,
            "injected_at": now,
            "params": payload,
        }
        self.pending_injection[service] = record
        event = self.add_event(
            {
                "type": "injection",
                "service": service,
                "severity": "warning",
                "title": "Failure injected",
                "detail": f"{payload.get('mode', 'http_500')} @ rate={payload.get('rate', 0)}",
                "timestamp": now.isoformat(),
            }
        )
        return event

    def open_incident(
        self,
        service: str,
        value: float,
        baseline: float,
        z_score: float,
        severity: str,
        reason: str,
    ) -> Incident:
        now = utcnow()
        incident_id = self._next_id(now)
        pending = self.pending_injection.get(service, {})
        injected_at = pending.get("injected_at")
        mttd = None
        if injected_at:
            mttd = max(0.0, (now - injected_at).total_seconds())
            self.mttd_history.append(mttd)
        incident = Incident(
            id=incident_id,
            service=service,
            status="detected",
            severity=severity,
            value=value,
            baseline=baseline,
            z_score=z_score,
            reason=reason,
            injected_at=injected_at,
            detected_at=now,
            mttd_seconds=round(mttd, 3) if mttd is not None else None,
            injection=pending.get("params", {}),
        )
        incident.timeline.append(
            {
                "status": "INJECTED",
                "at": iso(injected_at),
                "label": "Failure injected",
            }
        )
        incident.timeline.append(
            {
                "status": "DETECTED",
                "at": iso(now),
                "label": "Statistical anomaly detected",
            }
        )
        self.incidents[incident_id] = incident
        self.open_by_service[service] = incident_id
        self.add_event(
            {
                "type": "anomaly",
                "service": service,
                "severity": severity,
                "title": "Statistical anomaly detected",
                "detail": reason,
                "incident_id": incident_id,
                "value": value,
                "z_score": z_score,
                "mttd_seconds": incident.mttd_seconds,
                "timestamp": now.isoformat(),
            }
        )
        return incident

    def mark_alerted(self, incident: Incident, slack_result: dict[str, Any]) -> None:
        now = utcnow()
        incident.alerted_at = now
        incident.status = "alerted"
        incident.slack = slack_result
        incident.timeline.append(
            {
                "status": "ALERTED",
                "at": iso(now),
                "label": "Slack alert fired"
                if slack_result.get("sent")
                else "Slack skipped (no webhook)",
            }
        )
        self.add_event(
            {
                "type": "alert",
                "service": incident.service,
                "severity": incident.severity,
                "title": "Slack alert fired"
                if slack_result.get("sent")
                else "Alert generated (Slack not configured)",
                "detail": incident.id,
                "incident_id": incident.id,
                "timestamp": now.isoformat(),
            }
        )

    def recover(self, service: str, value: float, baseline: float) -> Optional[Incident]:
        incident_id = self.open_by_service.get(service)
        if not incident_id:
            return None
        incident = self.incidents[incident_id]
        now = utcnow()
        incident.recovered_at = now
        incident.status = "recovered"
        incident.timeline.append(
            {
                "status": "RECOVERED",
                "at": iso(now),
                "label": "Service recovered",
            }
        )
        self.open_by_service.pop(service, None)
        self.pending_injection.pop(service, None)
        self.add_event(
            {
                "type": "recovery",
                "service": service,
                "severity": "info",
                "title": "Service recovered",
                "detail": f"Error rate back to {value:.1%}",
                "incident_id": incident.id,
                "timestamp": now.isoformat(),
            }
        )
        return incident

    def mttd_summary(self) -> dict[str, Any]:
        history = self.mttd_history[-20:]
        current = history[-1] if history else None
        previous = history[-2] if len(history) >= 2 else None
        improvement = None
        if current is not None and previous not in (None, 0):
            improvement = round(((previous - current) / previous) * 100, 1)
        return {
            "current": current,
            "previous": previous,
            "history": history,
            "improvement_pct": improvement,
            "count": len(history),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "services": self.latest_metrics,
            "history": {k: list(v) for k, v in self.metric_history.items()},
            "incidents": [i.to_dict() for i in list(self.incidents.values())[::-1][:50]],
            "open_incidents": list(self.open_by_service.values()),
            "events": list(self.events)[:80],
            "mttd": self.mttd_summary(),
            "experiments": self.experiments[-10:],
        }
