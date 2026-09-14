from __future__ import annotations

from datetime import datetime, timedelta, timezone

from detector.rolling_zscore import Observation, RollingZScoreDetector


def obs(error_rate: float, requests: float = 80, n: int = 0) -> Observation:
    return Observation(
        timestamp=datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc) + timedelta(seconds=n),
        error_rate=error_rate,
        request_count=requests,
        request_rate=requests,
        p95_latency=0.04,
        success_count=1000,
        error_count=error_rate * 1000,
        health_value=1.0,
        injection_active=error_rate > 0.2,
    )


def test_warmup_does_not_trigger() -> None:
    detector = RollingZScoreDetector(
        window=20, z_threshold=3.0, consecutive_breaches=2, warmup_samples=8
    )
    for i in range(5):
        result = detector.observe(obs(0.8, n=i))
        assert result.triggered is False


def test_detects_error_rate_spike() -> None:
    detector = RollingZScoreDetector(
        window=30,
        z_threshold=3.0,
        consecutive_breaches=3,
        warmup_samples=10,
        min_request_count=10,
        alert_cooldown=0,
    )
    for i in range(15):
        detector.observe(obs(0.02, n=i))
    triggered = False
    for i in range(15, 20):
        result = detector.observe(obs(0.55, n=i))
        if result.triggered:
            triggered = True
            assert result.severity in {"high", "critical"}
            assert result.value >= 0.5
            break
    assert triggered, "expected a z-score / spike detection"


def test_requires_consecutive_breaches() -> None:
    detector = RollingZScoreDetector(
        window=30,
        z_threshold=3.0,
        consecutive_breaches=4,
        warmup_samples=10,
        min_request_count=10,
        alert_cooldown=0,
    )
    for i in range(12):
        detector.observe(obs(0.01, n=i))
    result = detector.observe(obs(0.7, n=12))
    assert result.triggered is False
    assert result.consecutive >= 1


def test_recovery_after_baseline_returns() -> None:
    detector = RollingZScoreDetector(
        window=30,
        z_threshold=3.0,
        consecutive_breaches=2,
        warmup_samples=8,
        min_request_count=10,
        recovery_observations=3,
        alert_cooldown=0,
    )
    for i in range(10):
        detector.observe(obs(0.02, n=i))
    detected = False
    for i in range(10, 14):
        result = detector.observe(obs(0.6, n=i))
        detected = detected or result.triggered
    assert detected
    recovered = False
    for i in range(14, 22):
        result = detector.observe(obs(0.02, n=i))
        recovered = recovered or result.recovered
    assert recovered


def test_min_request_volume_guard() -> None:
    detector = RollingZScoreDetector(
        window=20,
        z_threshold=2.0,
        consecutive_breaches=1,
        warmup_samples=5,
        min_request_count=50,
        alert_cooldown=0,
    )
    for i in range(8):
        detector.observe(obs(0.01, requests=80, n=i))
    result = detector.observe(obs(0.9, requests=2, n=8))
    assert result.triggered is False


def test_z_score_formula() -> None:
    detector = RollingZScoreDetector(window=10, warmup_samples=5)
    for i in range(10):
        detector.observe(obs(0.10, n=i))
    result = detector.observe(obs(0.40, n=10))
    assert result.z_score > 3
    assert result.baseline == 0.1
