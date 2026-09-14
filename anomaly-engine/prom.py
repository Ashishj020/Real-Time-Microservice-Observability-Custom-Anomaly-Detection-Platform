from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("prometheus")


class PrometheusClient:
    def __init__(self, base_url: str, timeout: float = 4.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def query_vec(self, expr: str) -> dict[str, float]:
        try:
            response = await self._client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": expr},
            )
            response.raise_for_status()
            payload = response.json()
            out: dict[str, float] = {}
            for row in payload.get("data", {}).get("result", []):
                service = row.get("metric", {}).get("service")
                value = row.get("value", [None, "0"])[1]
                if service:
                    out[service] = float(value)
            return out
        except Exception as exc:
            logger.warning("prometheus query failed: %s (%s)", expr, exc)
            return {}

    async def collect_all(
        self,
        services: list[str],
        query_window: str,
        rate_window: str,
    ) -> dict[str, dict[str, Any]]:
        requests = await self.query_vec(
            f"sum by (service) (increase(http_requests_total[{query_window}]))"
        )
        errors = await self.query_vec(
            f"sum by (service) (increase(http_request_errors_total[{query_window}]))"
        )
        request_rate = await self.query_vec(
            f"sum by (service) (rate(http_requests_total[{rate_window}]))"
        )
        error_rate_abs = await self.query_vec(
            f"sum by (service) (rate(http_request_errors_total[{rate_window}]))"
        )
        p95 = await self.query_vec(
            "histogram_quantile(0.95, "
            f"sum by (service, le) (rate(http_request_duration_seconds_bucket[{rate_window}])))"
        )
        health = await self.query_vec("sum by (service) (service_health)")
        injection = await self.query_vec("sum by (service) (failure_injection_active)")
        success_total = await self.query_vec(
            "sum by (service) (http_requests_total) - sum by (service) (http_request_errors_total)"
        )
        error_total = await self.query_vec("sum by (service) (http_request_errors_total)")

        samples: dict[str, dict[str, Any]] = {}
        for service in services:
            req = requests.get(service, 0.0)
            err = errors.get(service, 0.0)
            rps = request_rate.get(service, 0.0)
            err_rps = error_rate_abs.get(service, 0.0)
            error_rate = (err / req) if req > 0 else 0.0
            if rps > 0 and err_rps:
                error_rate = max(error_rate, err_rps / rps)
            samples[service] = {
                "service": service,
                "request_count": req,
                "error_count_window": err,
                "error_rate": min(1.0, max(0.0, error_rate)),
                "request_rate": rps,
                "p95_latency": p95.get(service, 0.0),
                "health_value": health.get(service, 1.0),
                "injection_active": injection.get(service, 0.0) > 0,
                "success_count": max(success_total.get(service, 0.0), 0.0),
                "error_count": max(error_total.get(service, 0.0), 0.0),
            }
        return samples
