"""Provision and drive the cookbook's slice of a REAL running NavFlow (`navflow up`).

Design principle: the cookbook is a *guest* on the user's daemon. It never mutates the user's
existing sources/views/triggers and never relies on catalog import (which is one-shot and would
merge into whatever is already there). Instead it creates its OWN objects, all under a namespace
prefix (default `sre_`), directly via the daemon's REST API — so they're unmistakably
cookbook-owned, isolated from the user's data, and removable in one call.

  setup()      create the sre_* sources, view, and triggers fresh (clean slate each run)
  teardown()   delete exactly those sre_* objects — the daemon is left as we found it
  push_deploy / push_config   feed the platform's deploy + config into the sre_ webhook sources
  query_timeline()            read the correlated timeline NavFlow serves (for the run's output)
  subscribe / unsubscribe     wire a webhook to a trigger so a push can wake the agent

Daemon: NAVFLOWD_URL (default http://127.0.0.1:8787). The agent's MCP endpoint is separate —
see navflow_agent.py (NAVFLOW_MCP_URL, `navflow mcp`).
"""
import os

import httpx

NAVFLOWD_URL = os.getenv("NAVFLOWD_URL", "http://127.0.0.1:8787")

# Everything the cookbook creates is prefixed, so it never collides with the user's own sources
# (their real systems, or the product's bundled demo) and is obvious in the console.
NS = os.getenv("NAVFLOW_COOKBOOK_NS", "sre_")

S_METRICS, S_LOGS, S_ALERTS = NS + "metrics", NS + "logs", NS + "alerts"
S_DEPLOYS, S_CONFIG, S_MEMORY = NS + "deploys", NS + "config", NS + "memory"
VIEW = NS + "service_timeline"
T_ERROR, T_SLOW = NS + "error_spike", NS + "slow_responses"
KEY = "api-server"

# Which of our triggers fires for which incident shape.
TRIGGER_FOR = {
    "error_spike": T_ERROR,
    "dependency_outage": T_ERROR,
    "db_pool_exhaustion": T_SLOW,
    "latency_regression": T_SLOW,
}

# ── Object specs (created via REST, namespaced) ─────────────────────────────────────────────
SOURCES = [
    {"name": S_METRICS, "connector": "prometheus", "poll": "5s", "config": {
        "url": "http://localhost:9090",
        "default_key": KEY,
        "labels": [{"name": "service", "field": "service"}],
        "queries": [
            {"promql": 'sum(rate(http_requests_total{status=~"5.."}[1m])) by (service)',
             "event_type": "5xx_rate", "field": "rate_5xx", "text": "5xx rate {service}={val}/s"},
            {"promql": 'histogram_quantile(0.99, sum(rate(http_request_duration_milliseconds_bucket[2m])) by (le, service))',
             "event_type": "p99", "field": "p99_ms", "text": "p99 {service}={val}ms"},
            {"promql": "db_pool_size", "event_type": "db_pool", "field": "db_pool_size",
             "text": "db_pool_size={val}"},
            {"promql": "db_connections_active", "event_type": "db_active",
             "field": "db_connections_active", "text": "db_connections_active={val}"},
            {"promql": "dependency_up", "event_type": "dependency", "field": "dependency_up",
             "text": "dependency {dependency} up={val}"},
        ],
    }},
    {"name": S_LOGS, "connector": "docker_logs", "poll": "5s", "config": {
        "container": "navflow-cookbook-sre-api",   # container_name in platform/docker-compose.yml
        "key": KEY,
        "match": "error|exhaust|timeout|pool|unreachable|KeyError|500",
    }},
    {"name": S_ALERTS, "connector": "alerts", "poll": "5s", "config": {
        "url": "http://localhost:9090", "key": KEY, "threshold": 5,
        "ratio_promql": '100*sum(rate(http_requests_total{status=~"5.."}[1m]))/sum(rate(http_requests_total[1m]))',
    }},
    # Deploy + config are pushed by run.py (POST /ingest/<key>) — the daemon assigns the ingest key.
    {"name": S_DEPLOYS, "connector": "webhook", "poll": "5s", "config": {
        "key_field": "service", "event_type": "deploy",
        "text_template": "deploy {commit} by {author} — {message}",
    }},
    {"name": S_CONFIG, "connector": "webhook", "poll": "5s", "config": {
        "key_field": "service", "event_type": "config",
        "text_template": "api-server config: {summary}",
    }},
    # The agent's own memory lane. Pre-creating it (namespaced) means the `remember` tool writes
    # HERE — the daemon uses the first existing memory-connector source instead of auto-provisioning
    # a bare `agent_memory` — so the write-back stays inside the cookbook's namespace and is torn
    # down with everything else. It's in the view, so a past conclusion shows up in later timelines.
    {"name": S_MEMORY, "connector": "memory", "poll": "5s", "config": {"key": KEY}},
]

# sre_alerts is deliberately NOT in the view: its FIRING lines are a 5s-sampled restatement of the
# 5xx rate already in sre_metrics (the baseline doesn't fetch alerts either — it reads the raw rate
# and infers the same thing). Keeping it here just padded every correlated read with ~12 redundant
# lines. The source still exists (Explore, and as a possible trigger input); it's just not in the read.
VIEW_SPEC = {"name": VIEW, "key_field": "service",
             "sources": [S_LOGS, S_METRICS, S_DEPLOYS, S_CONFIG, S_MEMORY]}

TRIGGERS = [
    {"name": T_ERROR, "view": VIEW, "cooldown": "5m",
     "condition": {"aggregate": "max", "field": "rate_5xx", "predicate": "> 1.0",
                   "window": "1m", "group_by": ["key_value"]},
     "emit": {"kind": T_ERROR, "context_window": "15m"}},
    {"name": T_SLOW, "view": VIEW, "cooldown": "30s",
     "condition": {"aggregate": "max", "field": "p99_ms", "predicate": "> 1000",
                   "window": "1m", "group_by": ["key_value"]},
     "emit": {"kind": T_SLOW, "context_window": "15m"}},
]


# ── HTTP helpers ────────────────────────────────────────────────────────────────────────────
async def _req(method: str, path: str, **kw):
    async with httpx.AsyncClient(timeout=20) as cx:
        return await cx.request(method, f"{NAVFLOWD_URL}{path}", **kw)


async def _get_json(path: str):
    return (await _req("GET", path)).json()


async def _delete(path: str):
    """Best-effort delete; ignore 404 (already gone)."""
    r = await _req("DELETE", path)
    if r.status_code not in (200, 204, 404):
        r.raise_for_status()


# ── Provisioning ────────────────────────────────────────────────────────────────────────────
async def _daemon_up() -> None:
    try:
        await _get_json("/health")
    except Exception:
        raise SystemExit(
            f"NavFlow daemon is not reachable at {NAVFLOWD_URL}.\n"
            "Start it:  navflow up            (install with: uv tool install navflow)\n"
            "and, in another shell, the MCP endpoint the agent connects to:  navflow mcp\n"
            "(or set NAVFLOWD_URL if the daemon runs elsewhere).")


async def teardown() -> None:
    """Remove exactly the cookbook's objects (triggers → view → sources). User data untouched."""
    for t in TRIGGERS:
        await _delete(f"/api/triggers/{t['name']}")
    await _delete(f"/api/views/{VIEW}")
    for s in SOURCES:
        await _delete(f"/api/sources/{s['name']}?purge_events=true")


async def setup() -> None:
    """Create the cookbook's sre_* objects fresh. Idempotent via teardown-then-create, so every
    run starts from a clean, correctly-configured slate without touching anything else."""
    await _daemon_up()
    await teardown()   # clear any objects left by a previous cookbook run
    async with httpx.AsyncClient(timeout=20) as cx:
        for s in SOURCES:
            r = await cx.post(f"{NAVFLOWD_URL}/api/sources", json=s)
            r.raise_for_status()
        r = await cx.post(f"{NAVFLOWD_URL}/api/views", json=VIEW_SPEC)
        r.raise_for_status()
        for t in TRIGGERS:
            r = await cx.post(f"{NAVFLOWD_URL}/api/triggers", json=t)
            r.raise_for_status()
    print(f"NavFlow ready at {NAVFLOWD_URL}: created {len(SOURCES)} sources, view {VIEW!r}, "
          f"triggers {[t['name'] for t in TRIGGERS]} (namespace {NS!r})")


# ── Runtime I/O ─────────────────────────────────────────────────────────────────────────────
async def _ingest_key(source: str) -> str:
    """The daemon assigns webhook sources an ingest key; read it back to push events."""
    src = await _get_json(f"/api/sources/{source}")
    return src.get("ingest_key") or source


async def ingest(source: str, payload: dict) -> None:
    key = await _ingest_key(source)
    await _req("POST", f"/ingest/{key}", json=payload)


async def push_deploy(entry: dict) -> None:
    """Forward the platform's newest changelog 'deploy' into the sre_deploys source."""
    await ingest(S_DEPLOYS, {
        "service": KEY,
        "commit": entry.get("commit", "unknown"),
        "author": entry.get("author", "system"),
        "message": entry.get("message", ""),
    })


async def push_config(cfg: dict) -> None:
    """Forward the platform's current config into the sre_config source (raw, no drift flags)."""
    summary = ", ".join(f"{k}={v}" for k, v in cfg.items())
    await ingest(S_CONFIG, {"service": KEY, "summary": summary})


async def query_timeline(window: str = "15m") -> str:
    """The correlated timeline NavFlow serves for the affected service — i.e. what the agent's
    single read returns. Used to show NavFlow's own output in the run summary."""
    r = await _req("POST", "/query", json={"view": VIEW, "key": KEY, "window": window, "client": "cookbook"})
    return r.json().get("payload", "")


async def subscribe(trigger: str, url: str) -> str:
    r = await _req("POST", "/subscribe", json={"trigger": trigger, "url": url})
    r.raise_for_status()
    return r.json()["subscription_id"]


async def unsubscribe(sub_id: str) -> None:
    await _req("POST", "/unsubscribe", json={"subscription_id": sub_id})
