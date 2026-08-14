"""The baseline: a provider-style SRE agent that wraps each system as its own tool and fans out
across them on every investigation. This is the read path Tares collapses.

Runs on the plain Anthropic SDK's Tool Runner: the 5 tools below are registered directly (in-process
functions that hit the platform), so the model's context carries exactly these 5 small schemas.
"""
import re

from anthropic import beta_async_tool

import platform_client as pc


@beta_async_tool
async def get_service_health() -> str:
    """Overview of all services: 5xx rates, p99 latency, DB pool size/usage, dependency health."""
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
    return "\n".join(lines)


@beta_async_tool
async def query_metrics(promql: str) -> str:
    """Run an arbitrary PromQL query against Prometheus and return the result rows."""
    res = await pc.prom(promql)
    return "\n".join(f"{s['metric']} = {s['value'][1]}" for s in res) or "(no data)"


@beta_async_tool
async def get_logs() -> str:
    """Recent error/warning logs from the api-server container."""
    raw = pc.get_api_logs(250)
    lines = [l for l in raw.splitlines()
             if re.search(r"error|exhaust|timeout|pool|unreachable|KeyError", l, re.I)][-8:]
    return "\n".join(lines) or "(no error logs)"


@beta_async_tool
async def get_config() -> str:
    """Current api-server config (the lever values an SRE inspects for misconfiguration)."""
    return str(await pc.get_config())


@beta_async_tool
async def get_recent_deploys() -> str:
    """Recent deploys / config changes (most recent last)."""
    changes = await pc.get_changelog(8)
    return "\n".join(f"{c['commit']} {c['author']}: {c['message']}"
                     for c in changes if c["lever"] != "reset") or "(no recent deploys)"


READ_TOOLS = {"get_service_health", "query_metrics", "get_logs", "get_config", "get_recent_deploys"}
TOOLS = [get_service_health, query_metrics, get_logs, get_config, get_recent_deploys]

SYSTEM_PROMPT = """You are an expert SRE incident response bot. Investigate production incidents
quickly and thoroughly using your tools.

Approach: start with get_service_health, drill into error rates and latency with query_metrics,
check container logs, inspect the current config for misconfiguration, and check recent deploys
for anything that changed. Correlate symptoms to a root cause and explain your reasoning."""
