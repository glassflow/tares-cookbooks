"""SRE sources for the NavFlow data plane, reading from the running platform.

These plug the demo's signals (Prometheus metrics, container logs, the api-server's config and
deploy log) into navflow's DataPlane, so one `query` returns them correlated. Query-time pull
for now — swap for continuous ingest later without touching the agent.
"""
import re
import time

from navflow import DataPlane, Record
import platform_client as pc

dp = DataPlane()


@dp.source("metrics")
async def metrics(key, window):
    recs = []
    err = await pc.prom('sum(rate(http_requests_total{status=~"5.."}[1m])) by (service)')
    hot = [f"{s['metric'].get('service','?')}={float(s['value'][1]):.2f}/s"
           for s in sorted(err, key=lambda r: -float(r["value"][1])) if float(s["value"][1]) > 0.05]
    if hot:
        recs.append(Record("metrics", "5xx rate by service: " + ", ".join(hot)))
    p99 = await pc.prom('histogram_quantile(0.99, sum(rate(http_request_duration_milliseconds_bucket[2m])) by (le, service))')
    slow = [f"{s['metric'].get('service','?')}={float(s['value'][1]):.0f}ms"
            for s in p99 if s["value"][1] not in ("NaN",) and float(s["value"][1]) > 300]
    if slow:
        recs.append(Record("metrics", "p99 latency: " + ", ".join(slow)))
    pool = await pc.prom_scalar("db_pool_size")
    active = await pc.prom_scalar("db_connections_active")
    if pool is not None:
        recs.append(Record("metrics", f"db_pool_size={pool:.0f}, db_connections_active={active:.0f}"))
    deps = await pc.prom("dependency_up")
    down = [s["metric"].get("dependency") for s in deps if float(s["value"][1]) == 0]
    if down:
        recs.append(Record("metrics", f"dependency down: {', '.join(down)}"))
    return recs


@dp.source("config")
async def config(key, window):
    # Hand over the raw config as-is. The agent decides what looks wrong — no drift flagging here.
    c = await pc.get_config()
    return [Record("config", "api-server config: " + ", ".join(f"{k}={v}" for k, v in c.items()))]


@dp.source("deploys")
async def deploys(key, window):
    now = time.time()
    out = []
    for c in await pc.get_changelog(8):
        if c["lever"] == "reset":
            continue
        out.append(Record("deploys",
                          f"deploy {c['commit']} by {c['author']} — '{c['message']}'",
                          ago=max(1.0, now - c["ts"])))
    return out[-2:]


@dp.source("logs")
async def logs(key, window):
    raw = pc.get_api_logs(250)
    pat = re.compile(r"error|exhaust|timeout|pool|unreachable|KeyError", re.I)
    lines = [l.split("| ", 1)[-1].strip() for l in raw.splitlines() if pat.search(l)][-4:]
    return [Record("logs", "\n".join(lines), ago=1.0)] if lines else []


@dp.source("alerts")
async def alerts(key, window):
    ratio = await pc.prom_scalar(
        '100*sum(rate(http_requests_total{status=~"5.."}[1m]))/sum(rate(http_requests_total[1m]))', 0.0)
    if ratio and ratio > 5:
        return [Record("alerts", f"FIRING (critical): HighErrorRate {ratio:.0f}% on api-server")]
    return []


dp.define_view("service_timeline", key_field="service",
               sources=["deploys", "config", "logs", "metrics", "alerts"])
