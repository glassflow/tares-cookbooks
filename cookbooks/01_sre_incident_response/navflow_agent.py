"""The NavFlow read path: the same agent as the baseline, with the fan-out tools replaced by one
in-process `query(view, key, window)` served by the NavFlow DataPlane (see `sources.py`).
"""
from claude_agent_sdk import ClaudeAgentOptions
from navflow import make_navflow_mcp, Trigger

import platform_client as pc
from sources import dp
from harness import MODEL

navflow_server = make_navflow_mcp(dp)

SYSTEM_PROMPT = """You are an expert SRE incident response bot. You have one data tool:
query(view, key, window). It returns a single time-ordered view of everything that happened to a
service — metrics, logs, config, deploys, alerts — already correlated.

Approach: call query for the affected service over a recent window
(view=service_timeline, key=api-server, window=15m), read the unified timeline, trace the causal
chain from the symptoms back to the root cause, and explain your reasoning. Only call query again
if you genuinely need more."""

options = ClaudeAgentOptions(
    system_prompt=SYSTEM_PROMPT,
    mcp_servers={"navflow": navflow_server},
    allowed_tools=["mcp__navflow__query"],
    permission_mode="acceptEdits",
    model=MODEL,
)


async def spike_condition():
    """Trigger: any service's 5xx rate spikes above the baseline noise."""
    res = await pc.prom('sum(rate(http_requests_total{status=~"5.."}[1m])) by (service)')
    for s in res:
        if float(s["value"][1]) > 1.0:
            return {"service": s["metric"].get("service"), "rate": round(float(s["value"][1]), 2)}
    return False


trigger = Trigger("error_spike", dp, "service_timeline", "api-server", spike_condition)
