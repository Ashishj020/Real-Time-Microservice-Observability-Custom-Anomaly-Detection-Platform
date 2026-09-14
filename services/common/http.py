from __future__ import annotations

from typing import Any, Optional

import httpx


async def call_service(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: Optional[dict[str, Any]] = None,
    timeout: float = 3.0,
) -> tuple[int, Any]:
    try:
        response = await client.request(method, url, json=json, timeout=timeout)
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}
        return response.status_code, body
    except httpx.RequestError as exc:
        return 503, {"error": "upstream_unavailable", "detail": str(exc), "url": url}
