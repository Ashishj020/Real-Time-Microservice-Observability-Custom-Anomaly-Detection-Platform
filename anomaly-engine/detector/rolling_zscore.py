from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Observation:
    timestamp: datetime
    error_rate: float
    request_count: float
    request_rate: float
    p95_latency: float
    success_count: float
    error_count: float
    health_value: float
    injection_active: bool


@dataclass
class DetectionResult:
    triggered: bool
    recovered: bool
    z_score: float
    baseline: float
    sigma: float
    value: float
    severity: str
    reason: str
    consecutive: int


class RollingZScoreDetector:
    """Online rolling z-score detector with persistence and cooldown safeguards."""

    def __init__(
        self,
        window: int = 60,
        z_threshold: float = 3.0,
        min_request_count: int = 20,
        consecutive_breaches: int = 3,
        alert_cooldown: int = 30,
        recovery_observations: int = 5,
        warmup_samples: int = 12,
    ) -> None:
        self.window = max(8, window)
        self.z_threshold = z_threshold
        self.min_request_count = min_request_count
        self.consecutive_breaches = max(1, consecutive_breaches)
        self.alert_cooldown = alert_cooldown
        self.recovery_observations = max(1, recovery_observations)
        self.warmup_samples = max(5, warmup_samples)
        self.history: Deque[float] = deque(maxlen=self.window)
        self.breach_streak = 0
        self.recovery_streak = 0
        self.in_incident = False
        self.last_alert_at: Optional[datetime] = None
        self.last_z = 0.0
        self.last_baseline = 0.0
        self.last_sigma = 0.0

    def configure(
        self,
        *,
        window: Optional[int] = None,
        z_threshold: Optional[float] = None,
        min_request_count: Optional[int] = None,
        consecutive_breaches: Optional[int] = None,
        alert_cooldown: Optional[int] = None,
        recovery_observations: Optional[int] = None,
        warmup_samples: Optional[int] = None,
    ) -> None:
        if window is not None:
            existing = list(self.history)
            self.window = max(8, window)
            self.history = deque(existing[-self.window :], maxlen=self.window)
        if z_threshold is not None:
            self.z_threshold = z_threshold
        if min_request_count is not None:
            self.min_request_count = min_request_count
        if consecutive_breaches is not None:
            self.consecutive_breaches = max(1, consecutive_breaches)
        if alert_cooldown is not None:
            self.alert_cooldown = alert_cooldown
        if recovery_observations is not None:
            self.recovery_observations = max(1, recovery_observations)
        if warmup_samples is not None:
            self.warmup_samples = max(5, warmup_samples)

    def snapshot(self) -> dict[str, float | int | bool]:
        return {
            "window": self.window,
            "z_threshold": self.z_threshold,
            "min_request_count": self.min_request_count,
            "consecutive_breaches": self.consecutive_breaches,
            "alert_cooldown": self.alert_cooldown,
            "recovery_observations": self.recovery_observations,
            "warmup_samples": self.warmup_samples,
            "history_len": len(self.history),
            "in_incident": self.in_incident,
            "breach_streak": self.breach_streak,
        }

    def _stats(self) -> tuple[float, float]:
        values = list(self.history)
        n = len(values)
        if n == 0:
            return 0.0, 0.0
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
        return mean, math.sqrt(variance)

    def _severity(self, z: float, error_rate: float) -> str:
        if z >= 5.0 or error_rate >= 0.4:
            return "critical"
        if z >= self.z_threshold or error_rate >= 0.2:
            return "high"
        return "warning"

    def _in_cooldown(self, now: datetime) -> bool:
        if self.last_alert_at is None:
            return False
        return (now - self.last_alert_at).total_seconds() < self.alert_cooldown

    def observe(self, observation: Observation) -> DetectionResult:
        now = observation.timestamp
        value = max(0.0, min(1.0, observation.error_rate))
        baseline, sigma = self._stats()
        safe_sigma = sigma if sigma > 1e-6 else 1e-6
        z = (value - baseline) / safe_sigma if self.history else 0.0
        self.last_z = z
        self.last_baseline = baseline
        self.last_sigma = sigma

        enough_volume = observation.request_count >= self.min_request_count
        warmed_up = len(self.history) >= self.warmup_samples
        min_lift = 0.08
        material = value >= baseline + min_lift and value >= 0.10
        elevated = z >= self.z_threshold and material
        absolute_spike = (
            warmed_up and enough_volume and value >= max(0.15, baseline + 0.12)
        )

        if enough_volume and warmed_up and (elevated or absolute_spike):
            self.breach_streak += 1
            self.recovery_streak = 0
        else:
            if self.in_incident and (not elevated) and value <= max(
                baseline * 1.8, baseline + 0.03
            ):
                self.recovery_streak += 1
            elif not self.in_incident:
                self.recovery_streak = 0
            if not elevated and not absolute_spike:
                self.breach_streak = 0

        triggered = False
        recovered = False
        reason = "nominal"

        if (
            not self.in_incident
            and enough_volume
            and warmed_up
            and self.breach_streak >= self.consecutive_breaches
            and not self._in_cooldown(now)
        ):
            triggered = True
            self.in_incident = True
            self.last_alert_at = now
            self.recovery_streak = 0
            reason = (
                f"z-score {z:.2f} >= {self.z_threshold} for "
                f"{self.breach_streak} consecutive samples"
            )
            if absolute_spike and z < self.z_threshold:
                reason = (
                    f"absolute error-rate spike {value:.2%} vs baseline {baseline:.2%} "
                    f"persisted for {self.breach_streak} samples"
                )

        if (
            self.in_incident
            and not triggered
            and self.recovery_streak >= self.recovery_observations
        ):
            recovered = True
            self.in_incident = False
            self.breach_streak = 0
            self.recovery_streak = 0
            reason = "error rate returned to baseline"

        if not self.in_incident and enough_volume:
            self.history.append(value)

        return DetectionResult(
            triggered=triggered,
            recovered=recovered,
            z_score=round(z, 3),
            baseline=round(baseline, 4),
            sigma=round(sigma, 4),
            value=round(value, 4),
            severity=self._severity(z, value) if triggered or self.in_incident else "info",
            reason=reason,
            consecutive=self.breach_streak,
        )
