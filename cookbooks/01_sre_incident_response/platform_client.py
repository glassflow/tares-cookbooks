"""Talk to the running `platform/` demo: Prometheus, the api-server admin plane, docker logs."""
import os
import subprocess
from pathlib import Path

import httpx

API = os.getenv("API_URL", "http://localhost:8080")
PROM = os.getenv("PROM_URL", "http://localhost:9090") + "/api/v1/query"
PLATFORM_DIR = Path(__file__).resolve().parents[2] / "platform"
COMPOSE = ["docker", "compose", "-f", str(PLATFORM_DIR / "docker-compose.yml")]


async def prom(expr: str):
    async with httpx.AsyncClient(timeout=10) as cx:
        r = await cx.get(PROM, params={"query": expr})
    return r.json().get("data", {}).get("result", [])


async def prom_scalar(expr: str, default=None):
    res = await prom(expr)
    if res and res[0]["value"][1] not in ("NaN", "+Inf", "-Inf"):
        return float(res[0]["value"][1])
    return default


async def get_config() -> dict:
    async with httpx.AsyncClient(timeout=10) as cx:
        return (await cx.get(f"{API}/admin/config")).json()


async def get_changelog(limit: int = 10):
    async with httpx.AsyncClient(timeout=10) as cx:
        return (await cx.get(f"{API}/admin/changelog", params={"limit": limit})).json().get("changes", [])


def get_api_logs(lines: int = 250) -> str:
    out = subprocess.run(COMPOSE + ["logs", "--tail", str(lines), "api-server"],
                         capture_output=True, text=True, timeout=25, cwd=str(PLATFORM_DIR))
    return out.stdout


async def inject(lever: str, value):
    async with httpx.AsyncClient(timeout=10) as cx:
        await cx.post(f"{API}/admin/fault", json={"lever": lever, "value": value})


async def reset():
    async with httpx.AsyncClient(timeout=10) as cx:
        await cx.post(f"{API}/admin/reset")
