"""The NavFlow read path: the same agent as the baseline, but its fan-out tools are replaced by one
query(view, key, window) tool that calls the navflow-mvp service (navflowd) — which ingested the
platform's signals (metrics, logs, config, deploys, alerts) into DuckDB and serves them correlated.
"""
import os

import httpx
from claude_agent_sdk import tool, create_sdk_mcp_server

NAVFLOWD = os.environ.get("NAVFLOWD_URL", "http://127.0.0.1:8787")


@tool(
    "query",
    "Read ONE time-ordered, correlated view of everything that happened to a service in a window: "
    "metrics, logs, config, deploys, and alerts, already merged. Call once for the affected service.",
    {"type": "object", "properties": {
        "view": {"type": "string"}, "key": {"type": "string"}, "window": {"type": "string"}},
     "required": ["view", "key", "window"]},
)
async def navflow_query(args):
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post(f"{NAVFLOWD}/query", json={
            "view": args.get("view", "service_timeline"),
            "key": args.get("key", "api-server"),
            "window": args.get("window", "15m")})
    return {"content": [{"type": "text", "text": r.json()["payload"]}]}


navflow_server = create_sdk_mcp_server(name="navflow", version="0.1.0", tools=[navflow_query])

SYSTEM_PROMPT = """You are an expert SRE incident response bot. You have one data tool:
query(view, key, window). It returns a single time-ordered view of everything that happened to a
service — metrics, logs, config, deploys, alerts — already correlated.

Approach: call query for the affected service over a recent window
(view=service_timeline, key=api-server, window=15m), read the unified timeline, trace the causal
chain from the symptoms back to the root cause, and explain your reasoning. Only call query again
if you genuinely need more."""
