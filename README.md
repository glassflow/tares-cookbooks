# NavFlow Cookbooks

Companion cookbooks to the agent cookbooks shipped by model providers (Anthropic, OpenAI,
…). Each one takes a published agent, keeps it exactly as-is, and **replaces only its read
path** with NavFlow — then measures the difference on a real, running system.

The point: an agent built the provider's way fans out across many tools to gather context
on every step. NavFlow ingests those sources once and serves the agent a single, correlated
query (and can trigger it with the context already attached). Same agent, same answer, far
fewer calls.

## Layout

```
platform/     ← the deployable demo system you run agents against
                  app/api_server.py   multi-lever fault-injecting API server (FastAPI + Prometheus)
                  docker-compose.yml, prometheus.yml, grafana/   one-command local stack
cookbooks/    ← one dir per cookbook
                  01_sre_incident_response/   Anthropic's SRE agent vs the NavFlow read path
```

`platform/` is the testbed; the **NavFlow read path is served by the sibling `navflow-mvp` repo**
(the `navflowd` service), which ingests the platform's signals into DuckDB and serves one correlated
`query`. A new cookbook is mostly: add a NavFlow catalog for the new signals, point a baseline agent
and a NavFlow agent at the same scenario, and measure.

## The platform: one system, several injectable incidents

Anthropic's SRE demo exposes a single lever (DB pool size), so it can only stage one incident.
Ours keeps the same clean Prometheus metric shape and Grafana dashboard, but the API server
exposes several **independent** faults, each with distinguishable metrics, logs, and a
"deploy" changelog entry (the correlation signal an SRE agent needs):

| Incident | Lever | What it looks like |
|---|---|---|
| DB pool exhaustion | `db_pool_size` | pool-exhausted logs, `db_connections_active` pinned, 500s on `/api/users` |
| Latency regression | `inject_latency_ms` | p99 spikes, pool healthy, no error logs |
| Error spike (bad deploy) | `error_rate` | app-exception logs, DB healthy |
| Dependency outage | `dependency_down` | `dependency_up{...}=0`, "upstream unreachable" logs on `/api/orders` |

Inject and clear at runtime, no redeploy:

```bash
curl -XPOST localhost:8080/admin/fault   -d '{"lever":"db_pool_size","value":1}'
curl -XPOST localhost:8080/admin/fault   -d '{"lever":"inject_latency_ms","value":800}'
curl -XPOST localhost:8080/admin/fault   -d '{"lever":"dependency_down","value":"payments-api"}'
curl -XPOST localhost:8080/admin/reset
curl localhost:8080/admin/config      # the current config an agent inspects
curl localhost:8080/admin/changelog   # recent "deploys" — the root-cause correlation
```

## Each cookbook compares

- **Baseline** — the provider's agent, wrapping each source as its own tool (the read-path fan-out).
- **NavFlow read path** — the same agent with the tools replaced by one `query(view, key, window)`,
  served by the navflow-mvp service.

…against each injected incident, with read-call / turn / cost / accuracy measured. (NavFlow can also
*push* — `navflowd` watches the stream and wakes the agent with the timeline attached — but the
benchmark here measures the pull/read path.)

## Status

- [x] `platform/` — multi-lever fault-injecting API server + docker-compose (Prometheus, Grafana, traffic gen)
- [x] NavFlow read path served by the sibling **navflow-mvp** service (`navflowd`)
- [x] `cookbooks/01_sre_incident_response/` — baseline + NavFlow agents, `report.py` benchmark
- [ ] additional cookbooks (other providers / use cases)

See [`cookbooks/01_sre_incident_response/README.md`](cookbooks/01_sre_incident_response/README.md)
for the first walkthrough.
