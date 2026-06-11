"""The baseline: a provider-style SRE agent that wraps each source as its own tool and fans
out across them on every investigation. This is the read path NavFlow collapses."""
from claude_agent_sdk import ClaudeAgentOptions, tool, create_sdk_mcp_server

import platform_client as pc
from harness import MODEL


def _text(s: str):
    return {"content": [{"type": "text", "text": s}]}


@tool("get_service_health", "Overview of all services: 5xx rates, p99 latency, DB pool, dependencies.",
      {"type": "object", "properties": {}})
async def get_service_health(args):
    err = await pc.prom('sum(rate(http_requests_total{status=~"5.."}[1m])) by (service)')
    p99 = await pc.prom('histogram_quantile(0.99, sum(rate(http_request_duration_milliseconds_bucket[2m])) by (le, service))')
    pool = await pc.prom_scalar("db_pool_size")
    active = await pc.prom_scalar("db_connections_active")
    deps = await pc.prom("dependency_up")
    lines = ["5xx/s: " + ", ".join(f"{s['metric'].get('service','?')}={float(s['value'][1]):.2f}" for s in err)]
    lines.append("p99 ms: " + ", ".join(f"{s['metric'].get('service','?')}={float(s['value'][1]):.0f}"
                                         for s in p99 if s["value"][1] != "NaN"))
    lines.append(f"db_pool_size={pool}, db_connections_active={active}")
    lines.append("dependencies: " + ", ".join(f"{s['metric'].get('dependency')}={'up' if float(s['value'][1]) else 'DOWN'}" for s in deps))
    return _text("\n".join(lines))


@tool("query_metrics", "Run an arbitrary PromQL query.",
      {"type": "object", "properties": {"promql": {"type": "string"}}, "required": ["promql"]})
async def query_metrics(args):
    res = await pc.prom(args["promql"])
    return _text("\n".join(f"{s['metric']} = {s['value'][1]}" for s in res) or "(no data)")


@tool("get_logs", "Recent error logs from the api-server container.", {"type": "object", "properties": {}})
async def get_logs(args):
    import re
    raw = pc.get_api_logs(250)
    lines = [l for l in raw.splitlines() if re.search(r"error|exhaust|timeout|pool|unreachable|KeyError", l, re.I)][-8:]
    return _text("\n".join(lines) or "(no error logs)")


@tool("get_config", "Current api-server config (the lever values an SRE inspects for misconfiguration).",
      {"type": "object", "properties": {}})
async def get_config(args):
    return _text(str(await pc.get_config()))


@tool("get_recent_deploys", "Recent deploys / config changes (most recent last).",
      {"type": "object", "properties": {}})
async def get_recent_deploys(args):
    changes = await pc.get_changelog(8)
    return _text("\n".join(f"{c['commit']} {c['author']}: {c['message']}"
                           for c in changes if c["lever"] != "reset") or "(no recent deploys)")


READ_TOOLS = {"get_service_health", "query_metrics", "get_logs", "get_config", "get_recent_deploys"}
baseline_server = create_sdk_mcp_server(
    name="sre", version="0.1.0",
    tools=[get_service_health, query_metrics, get_logs, get_config, get_recent_deploys],
)

SYSTEM_PROMPT = """You are an expert SRE incident response bot. Investigate production incidents
quickly and thoroughly using your tools.

Approach: start with get_service_health, drill into error rates and latency with query_metrics,
check container logs, inspect the current config for misconfiguration, and check recent deploys
for anything that changed. Correlate symptoms to a root cause and explain your reasoning."""

options = ClaudeAgentOptions(
    system_prompt=SYSTEM_PROMPT,
    mcp_servers={"sre": baseline_server},
    allowed_tools=[f"mcp__sre__{t}" for t in READ_TOOLS],
    permission_mode="acceptEdits",
    model=MODEL,
)
