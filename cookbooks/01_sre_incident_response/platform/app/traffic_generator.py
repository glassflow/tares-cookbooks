"""Sends steady concurrent traffic so metrics always flow and faults become visible."""
import os
import random
import asyncio

import httpx

API = os.getenv("API_URL", "http://api-server:8080")
# Weight /api/users (the DB-bound path) so pool/latency faults show up clearly.
ENDPOINTS = ["/api/users", "/api/users", "/api/users", "/api/orders", "/api/stats"]
CONCURRENCY = int(os.getenv("CONCURRENCY", "12"))


async def worker(client: httpx.AsyncClient):
    while True:
        ep = random.choice(ENDPOINTS)
        try:
            await client.get(API + ep, timeout=10.0)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.05, 0.2))


async def main():
    print(f"traffic-generator → {API} (concurrency {CONCURRENCY})", flush=True)
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[worker(client) for _ in range(CONCURRENCY)])


if __name__ == "__main__":
    asyncio.run(main())
