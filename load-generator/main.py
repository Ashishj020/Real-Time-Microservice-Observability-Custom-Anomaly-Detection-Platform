from __future__ import annotations

import asyncio
import os
import random

import httpx

GATEWAY = os.getenv("GATEWAY_URL", "http://api-gateway:8000")
USERS = ["u-1001", "u-1002", "u-1003"]


async def one_cycle(client: httpx.AsyncClient) -> None:
    user_id = random.choice(USERS)
    roll = random.random()
    try:
        if roll < 0.45:
            await client.post(
                f"{GATEWAY}/api/checkout",
                json={"user_id": user_id, "amount": round(random.uniform(9, 80), 2)},
                timeout=5.0,
            )
        elif roll < 0.7:
            await client.get(f"{GATEWAY}/api/users/{user_id}", timeout=5.0)
        elif roll < 0.85:
            await client.get(f"{GATEWAY}/api/users/{user_id}/billing", timeout=5.0)
        elif roll < 0.95:
            await client.get(f"{GATEWAY}/api/payments", timeout=5.0)
        else:
            await client.post(
                f"{GATEWAY}/api/notify",
                json={"user_id": user_id, "template": "promo"},
                timeout=5.0,
            )
    except Exception:
        return


async def worker(name: int) -> None:
    async with httpx.AsyncClient() as client:
        while True:
            await one_cycle(client)
            await asyncio.sleep(random.uniform(0.04, 0.18))


async def main() -> None:
    await asyncio.sleep(3)
    await asyncio.gather(*(worker(i) for i in range(4)))


if __name__ == "__main__":
    asyncio.run(main())
