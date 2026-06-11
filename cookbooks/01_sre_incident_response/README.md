# 01 · SRE Incident Response

An SRE agent investigates a production incident two ways against the **same running system**:

1. **Baseline** — the provider-style agent: each signal (metrics, logs, config, deploys) is its
   own tool, and the agent fans out across them on every investigation.
2. **NavFlow read path** — the *same* agent and the *same* prompt, but the fan-out tools are
   replaced by a single `query(view, key, window)` that returns those signals already correlated.

A third variant, **NavFlow trigger**, skips the investigation start entirely: NavFlow watches the
system, fires when a condition trips, and wakes the agent with the correlated timeline already
attached — zero reads to begin.

Everything runs against the `platform/` demo (FastAPI + Postgres + Prometheus + Grafana), with a
real fault injected at runtime. The NavFlow side runs **in-process** (see `navflow/` and
`sources.py`) — no external service, so the cookbook is fully self-contained. Same incident, same
answer — the only thing that changes is how the agent reads.

## What you'll see

Each incident is injected, then run through the baseline and the NavFlow agent. Reads and turns are
the cache-independent contrast; cost is real API pricing (these runs use an API key, not subscription
auth). One run per incident:

| incident | baseline reads / turns | navflow reads / turns | baseline cost | navflow cost | both correct |
|---|---|---|---|---|---|
| db_pool_exhaustion | 7 / 9 | 1 / 3 | $0.5096 | $0.1308 | ✅ |
| latency_regression | 16 / 18 | 1 / 3 | $0.3648 | $0.1590 | ✅ |
| error_spike | 12 / 14 | 1 / 3 | $0.2550 | $0.1412 | ✅ |
| dependency_outage | 8 / 10 | 1 / 3 | $0.2240 | $0.1460 | ✅ |
| **total** | **43 / 51** | **4 / 12** | **$1.3534** | **$0.5771** | 4 / 4 |

**Baseline ÷ NavFlow: reads 10.8×, turns 4.2×, cost 2.3×.**

The agent reaches the same root cause either way. The NavFlow agent is dead flat at **1 read / 3
turns** on every incident; the baseline swings from 7 to 16 reads depending on how hard the incident
is to disambiguate. That consistency is itself the finding — the correlated query removes the search
variance, not just the call count.

Honest caveats: these are **single runs**, no averaging, so treat them as directional. The cost gap
(2.3×) is more modest than the read gap (10.8×) because cost is dominated by output and cache-read
tokens, not raw read count — collapsing 8 reads to 1 doesn't divide cost by 8. And
`latency_regression`'s 16-read baseline is exactly the fan-out variance a fluke-controlled benchmark
would average out; don't read the 16 as typical.

## Setup

From the repo root:

```bash
# 1. bring up the platform (api-server :8080, Prometheus :9090, Grafana :3000)
cd platform && docker compose up -d --build && cd ..

# 2. install navflow + the SDK into a venv
uv venv && uv pip install -e .

# 3. put ANTHROPIC_API_KEY in cookbooks/01_sre_incident_response/.env
#    The harness fails closed if it's missing — it will NOT fall back to subscription auth, so
#    the reported cost is real API billing.
```

Confirm the system is healthy before injecting anything:

```bash
curl -s localhost:8080/health      # {"status":"healthy", ...}
curl -s localhost:8080/admin/config
```

## Run an incident

```bash
cd cookbooks/01_sre_incident_response
python run.py latency_regression
```

`run.py` resets the system, injects the named fault, waits ~30s for the symptoms to register in
Prometheus, then runs the baseline agent, the NavFlow agent, and (if the condition fires) the
trigger path — printing a scoreboard and the NavFlow diagnosis. It resets to healthy on exit.

Incident names: `db_pool_exhaustion`, `latency_regression`, `error_spike`, `dependency_outage`
(default `latency_regression`).

To reproduce the full table above — all four incidents through both agents, one run each, with the
consolidated metrics (reads, turns, tokens incl. cache breakdown, real cost, accuracy):

```bash
python report.py
```

## How it works

Three "contestants," one shared scorer:

| file | role |
|---|---|
| `baseline_agent.py` | Defines the provider-style agent: 5 read tools (`get_service_health`, `query_metrics`, `get_logs`, `get_config`, `get_recent_deploys`) + its system prompt. |
| `navflow_agent.py` | Defines the same agent with one tool, `mcp__navflow__query`, plus the `error_spike` trigger. |
| `harness.py` | The shared stopwatch + scorer. `run_agent()` runs *any* agent's options, counts read/write calls, turns, cost, wall-clock, and collects the diagnosis text. Holds the shared task prompt. |
| `incidents.py` | The four incidents (fault lever + value) and `found_root_cause()`, the keyword grader. |
| `sources.py` | The NavFlow side: registers the demo's signals as data-plane sources and defines the `service_timeline` view. |
| `platform_client.py` | Thin I/O to the running platform — Prometheus queries, the admin config/changelog, docker logs, fault injection. Used by both agents and the runner. |
| `run.py` | Stages one incident and runs all three variants (baseline, NavFlow, trigger). |
| `report.py` | Runs all four incidents through baseline + NavFlow, one run each, and prints the consolidated metrics table. |

### Two kinds of prompt

- The **task prompt** (`INCIDENT_PROMPT` in `harness.py`) is identical for every agent — "something
  is wrong, investigate." Fairness: everyone gets the same job.
- The **system prompt** lives per-agent (in each `*_agent.py`), because the tools differ. The
  baseline's says "start with `get_service_health`, drill in with `query_metrics`…"; NavFlow's says
  "call `query(view=service_timeline, key=api-server, window=15m)` and trace the timeline."

### The NavFlow read path

The whole substitution is one hop, and it runs in-process — no external service. The agent calls
`query`, which resolves like this:

```
agent → mcp__navflow__query  (navflow/mcp.py)
                  │
                  ▼
        DataPlane.query(view, key, window)   (navflow/dataplane.py)
                  │  gathers the view's sources concurrently, merges, sorts by time
                  ▼
        sources.py  →  platform_client  →  Prometheus / logs / admin API
```

`sources.py` defines five sources (`metrics`, `config`, `deploys`, `logs`, `alerts`) and one view:

```python
dp.define_view("service_timeline", key_field="service",
               sources=["deploys", "config", "logs", "metrics", "alerts"])
```

The sources hand over **raw signals**, not conclusions — `config` returns the literal lever values,
`deploys` returns commit + author + message (no internal lever names), `metrics` returns the 5xx
rates and p99 it reads from Prometheus. The agent does the diagnosis; NavFlow only correlates. One
`query` returns the same facts the baseline gathered across 7–16 separate reads, already
time-ordered into a single timeline.

> Pull-at-query-time here for simplicity. Whether NavFlow pulls on demand or ingests continuously
> doesn't change the agent's path — only the data plane's internals, which can be swapped later for
> a real NavFlow deployment.

### The trigger path

`navflow_agent.py` also defines a `Trigger` watching the `service_timeline` for any service whose
5xx rate spikes past `1.0/s`. When it fires, the agent is woken with the timeline already in the
prompt (`WOKEN_PROMPT`), so it starts at **zero reads**. It fires on the error-rate incidents
(`error_spike`, `dependency_outage`); the timeout-shaped ones (`db_pool`, `latency`) keep raw 5xx
below the threshold, so they don't — tune the threshold/window in `spike_condition()` if you want
all four to fire.

## Grading

`found_root_cause(text, incident)` checks whether the agent's diagnosis mentions any of that
incident's `root_hint` keywords (e.g. `latency_regression` → `latency`, `inject_latency_ms`,
`audit`, `slow`). It's a coarse but consistent pass/fail applied identically to every variant.

The deploy "commit messages" are deliberately vague (`"Align resource limits with staging
environment"`, not `"set db_pool_size=1"`) so the agent has to *correlate* the deploy with the
symptoms and timing rather than read the answer off a config diff. That the NavFlow agent still
names the right deploy is the signal the correlation is doing real work.

## Extending to a new cookbook

`navflow/` and `platform/` are reused as-is. A new cookbook is mostly:

1. Write its `sources.py` — register the relevant signals as data-plane sources, define a view.
2. Point a baseline agent (provider-style, one tool per source) and a NavFlow agent (one `query`)
   at the same scenario.
3. Reuse `harness.run_agent()` to measure.
