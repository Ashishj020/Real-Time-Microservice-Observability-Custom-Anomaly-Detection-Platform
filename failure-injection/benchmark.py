from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

ENGINE = os.getenv("ANOMALY_ENGINE_URL", "http://localhost:8080")
RESULTS = Path(__file__).resolve().parents[1] / "benchmark-results.json"

BASELINE = {
    "profile": "baseline",
    "anomaly_window": 60,
    "z_score_threshold": 3.0,
    "min_request_count": 20,
    "consecutive_breaches": 3,
    "alert_cooldown": 15,
    "warmup_samples": 12,
}

OPTIMIZED = {
    "profile": "optimized",
    "anomaly_window": 20,
    "z_score_threshold": 2.5,
    "min_request_count": 8,
    "consecutive_breaches": 2,
    "alert_cooldown": 8,
    "warmup_samples": 6,
}


def wait_healthy(client: httpx.Client, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = client.get(f"{ENGINE}/health", timeout=3.0)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("anomaly engine did not become healthy")


def wait_no_open_incidents(client: httpx.Client, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"{ENGINE}/api/snapshot", timeout=5.0).json()
        if not snap.get("open_incidents"):
            payment = snap.get("services", {}).get("payment-service", {})
            if payment.get("error_rate", 1) < 0.08:
                return
        time.sleep(1)
    print("warning: proceeding while an incident may still be open")


def latest_incident(client: httpx.Client, after: str) -> Optional[dict[str, Any]]:
    incidents = client.get(f"{ENGINE}/api/incidents", timeout=5.0).json().get("incidents", [])
    for item in incidents:
        if item.get("service") == "payment-service" and (item.get("detected_at") or "") >= after:
            return item
    return None


def run_trial(client: httpx.Client, label: str, config: dict[str, Any], duration: float, rate: float) -> dict[str, Any]:
    client.post(f"{ENGINE}/api/config", json=config, timeout=5.0)
    time.sleep(8)
    wait_no_open_incidents(client)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    inject_at = time.time()
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from inject_failure import inject  # type: ignore

    inject("payment", duration=duration, rate=rate, mode="http_500", latency_ms=0)
    detected = None
    deadline = time.time() + duration + 20
    while time.time() < deadline:
        incident = latest_incident(client, started)
        if incident and incident.get("mttd_seconds") is not None:
            detected = incident
            break
        time.sleep(0.25)
    mttd = detected.get("mttd_seconds") if detected else None
    record = {
        "label": label,
        "config": config,
        "injected_at": inject_at,
        "detected_at": detected.get("detected_at") if detected else None,
        "incident_id": detected.get("id") if detected else None,
        "mttd_seconds": mttd,
        "status": "detected" if detected else "timeout",
    }
    client.post(f"{ENGINE}/api/experiments", json=record, timeout=5.0)
    time.sleep(duration + 2)
    wait_no_open_incidents(client, timeout=60)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline vs optimized MTTD experiment")
    parser.add_argument("--duration", type=float, default=35)
    parser.add_argument("--rate", type=float, default=0.85)
    args = parser.parse_args()

    with httpx.Client() as client:
        wait_healthy(client)
        print("Running baseline trial...")
        baseline = run_trial(client, "baseline", BASELINE, args.duration, args.rate)
        print(json.dumps(baseline, indent=2))
        print("Running optimized trial...")
        optimized = run_trial(client, "optimized", OPTIMIZED, args.duration, args.rate)
        print(json.dumps(optimized, indent=2))

    b = baseline.get("mttd_seconds")
    o = optimized.get("mttd_seconds")
    improvement = None
    if isinstance(b, (int, float)) and isinstance(o, (int, float)) and b > 0:
        improvement = round(((b - o) / b) * 100, 1)

    results = {
        "baseline": baseline,
        "optimized": optimized,
        "improvement_pct": improvement,
    }
    RESULTS.write_text(json.dumps(results, indent=2))
    print("\n=== MTTD EXPERIMENT ===")
    print(f"Baseline : {b} s")
    print(f"Optimized: {o} s")
    print(f"Improvement: {improvement}%")
    print(f"Wrote {RESULTS}")


if __name__ == "__main__":
    main()
