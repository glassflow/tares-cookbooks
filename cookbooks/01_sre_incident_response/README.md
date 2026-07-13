# 01 · AI SRE — Incident Response

An SRE agent investigates a production incident two ways against the **same running system**, read
through a **real, local NavFlow deployment**:

1. **Baseline** — the provider-style agent: each signal (metrics, logs, config, deploys) is its own
   tool, and the agent fans out across them on every investigation.
2. **NavFlow read path** — the *same* agent and the *same* prompt, but the fan-out tools are
   replaced by a single `query(view, key, window)` that NavFlow serves already correlated.

A third variant, **NavFlow trigger**, skips the investigation start entirely: NavFlow watches the
system, fires when a condition trips, and wakes the agent over a real webhook with the correlated
timeline already attached — zero reads to begin.

Everything runs against this cookbook's own `platform/` stack (FastAPI + Postgres + Prometheus +
Grafana) with a real fault injected at runtime, and against the running product (`navflow up` +
`navflow mcp`). Same incident, same answer — the only thing that changes is how the agent reads.

**Outcome measured:** tool calls, turns, wall-clock, input tokens, and cost — **measured only until
the root cause is found**. Both agents are read-only for that window (fair comparison), so the
numbers capture "cost/time to diagnose," nothing else. Cost is computed from token `usage` × the
published per-model pricing (`MODEL_PRICING` in `harness.py`) — the Messages API returns tokens, not
dollars — so treat it as directional, not a billing statement.

## What you'll see

Each incident is injected, then run through both agents. A representative real run
(`db_pool_exhaustion`, Sonnet 5):

| agent | reads | turns | input tokens | cost | root cause |
|---|---|---|---|---|---|
| baseline (fan-out) | 6 | 3 | 5,493 | $0.0262 | ✅ |
| navflow (one read) | 1 | 2 | 3,805 | $0.0194 | ✅ |
| navflow (triggered, pushed) | 0 | 1 | 2,459 | $0.0129 | ✅ |

Same diagnosis every way. The durable, model-independent finding is the **read collapse — many
targeted calls → one correlated read** (here 6 → 1; the baseline swings run to run depending on how
hard the incident is to disambiguate). Input tokens and cost come out **lower** for NavFlow too, and
lowest of all when the trigger *pushes* the timeline (zero reads). Exact dollars vary by model and
run — single runs, no averaging, treat as directional. (Note: weaker models like Haiku may over-fetch
by setting `include_payload=True` on the read, inflating NavFlow's tokens; Sonnet/Opus don't.)

**On the read-only measurement:** the baseline only ever reads, so to compare like-for-like the
NavFlow agent is measured read-only too. After the diagnosis, the NavFlow agent does one more thing
the baseline can't — it `remember()`s its conclusion back into NavFlow (`sre_memory`), so the next
incident's timeline arrives with the prior conclusion already in it. That write-back is a genuine
agent turn, printed in the run, but deliberately **left out of the scoreboard** (it happens after
the root cause is found).

## Prerequisites

The [repo prerequisites](../../README.md#prerequisites-shared-by-every-cookbook), in short:

```bash
# the product — leave both running
navflow up            # daemon + console → http://127.0.0.1:8787
navflow mcp           # agent MCP endpoint → http://127.0.0.1:8788/mcp   (second shell)
```

## Setup

```bash
# 1. bring up this cookbook's platform (api-server :8080, Prometheus :9090, Grafana :3000)
#    Pulls the pre-built api-server image. To modify ./app instead, build locally:
#    docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
cd platform && docker compose up -d && cd ..

# 2. from the repo root: venv + deps, then activate (or prefix runs with `uv run`)
uv venv && uv pip install -e . && source .venv/bin/activate

# 3. put ANTHROPIC_API_KEY in cookbooks/01_sre_incident_response/.env
#    The harness fails closed if it's missing — the runs are real API calls billed to that key.
```

Confirm the platform is healthy before injecting anything:

```bash
curl -s localhost:8080/health      # {"status":"healthy", ...}
```

## Run an incident

```bash
cd cookbooks/01_sre_incident_response
python run.py latency_regression
```

`run.py` creates the cookbook's own NavFlow objects (see below), resets the system, subscribes a
webhook to the incident's trigger, injects the fault, forwards the platform's deploy + config into
NavFlow, waits for symptoms to register, then runs the baseline agent, the NavFlow agent, and (if
the trigger fires) the woken agent. It prints a **scoreboard** (the read-path collapse) and **what
NavFlow served** (the single correlated timeline) — not a wall of agent prose. It resets to healthy
on exit. Watch every read and dispatch at <http://127.0.0.1:8787> → **Agents**.

Incident names: `db_pool_exhaustion`, `latency_regression`, `error_spike`, `dependency_outage`
(default `latency_regression`). `python run.py teardown` removes the cookbook's objects.

### The cookbook is a guest on your NavFlow

It never touches your existing sources or relies on catalog import (which is one-shot and would
merge into your data). Instead `navflow_client.setup()` creates its **own namespaced objects** via
the daemon's REST API — sources `sre_metrics` / `sre_logs` / `sre_alerts` / `sre_deploys` /
`sre_config` / `sre_memory`, view `sre_service_timeline`, triggers `sre_error_spike` /
`sre_slow_responses` (the
`sre_` prefix is configurable via `NAVFLOW_COOKBOOK_NS`). They're obvious in the console, isolated
from your data, and removed cleanly by `python run.py teardown`.

To reproduce the full table — all four incidents through both agents, with the consolidated metrics:

```bash
python report.py
```

## How it works

Three "contestants," one shared scorer:

| file | role |
|---|---|
| `baseline_agent.py` | The provider-style agent: 5 tools (`get_service_health`, `query_metrics`, `get_logs`, `get_config`, `get_recent_deploys`), each a `@beta_async_tool` that hits the platform directly. |
| `navflow_agent.py` | The NavFlow read path. `mcp_tools()` opens an MCP client session to the running `navflow mcp` and registers **only `query`** — even though the server advertises 13 tools, the model's context carries one schema. (It also wraps `remember` for the separate, unscored write-back.) |
| `harness.py` | The shared stopwatch + scorer. `run_agent()` drives the Anthropic SDK's **Tool Runner** (`client.beta.messages.tool_runner`) over exactly the tools you register, counts read/write calls (+ distinct tools), turns, wall-clock, streams progress live, sums token `usage`, and computes cost from `MODEL_PRICING`. Holds the shared task prompt. |
| `incidents.py` | The four incidents (fault lever + value), a human root-cause label, and `found_root_cause()`, the keyword grader. |
| `platform_client.py` | Thin I/O to the running platform — Prometheus queries, the admin config/changelog, docker logs, fault injection. Used by the baseline agent and the runner. |
| `navflow_client.py` | The cookbook's NavFlow provisioning + I/O: `setup()`/`teardown()` for the namespaced `sre_*` objects, deploy/config push, `query_timeline()`, and subscribe/unsubscribe for the trigger webhook. |
| `run.py` | Stages one incident and runs all three variants (baseline, NavFlow, trigger). |
| `report.py` | Runs all four incidents through baseline + NavFlow and prints the consolidated metrics table. |

### Two kinds of prompt

- The **task prompt** (`INCIDENT_PROMPT` in `harness.py`) is identical for every agent — "something
  is wrong, investigate." Fairness: everyone gets the same job.
- The **system prompt** lives per-agent (in each `*_agent.py`), because the tools differ. The
  baseline's says "start with `get_service_health`, drill in with `query_metrics`…"; NavFlow's says
  "call `query(view=sre_service_timeline, key=api-server, window=15m)` and trace the timeline."

### The NavFlow read path

Both agents run on the plain Anthropic SDK's **Tool Runner** — not the Claude Agent SDK / Claude
Code CLI. That's deliberate: *we* build each agent's tool list, so the model's context carries
exactly the tools we register — the baseline its 5 in-process tools, NavFlow **one** (`query`). The
cookbook opens its own MCP client session to `navflow mcp`, discovers its tools, and wraps only
`query` (`navflow_agent.mcp_tools()`), so the server's other 12 tools never enter the model's
context. Each `query` is one MCP hop to the `navflow up` daemon, which has been ingesting the
platform continuously via the cookbook's `sre_*` sources:

```
agent → query  (our MCP client → navflow mcp, :8788)
              │  MCP call_tool
              ▼
      navflowd  (navflow up, :8787)  →  DuckDB  →  sre_service_timeline view
              ▲  continuous ingest (poll / push)
      Prometheus · container logs · deploys+config (webhook)
```

> Why not the Claude Agent SDK? Mounting `navflow mcp` there loads *all 13* tool schemas into the
> model's context every turn (~3k tokens) — `allowed_tools` gates calling, not context. Owning the
> tools array (Tool Runner) is what lets NavFlow's read path be genuinely *one* tool.

`setup()` defines six sources and one view (`sre_service_timeline` over
`[sre_logs, sre_metrics, sre_deploys, sre_config, sre_memory]`, keyed by `service`).
`sre_memory` is the agent's own write-back lane, so a past conclusion shows up in later timelines.

The sources carry **raw signals**, not conclusions — `sre_config` is the literal lever values,
`sre_deploys` is commit + author + message (no internal lever names), `sre_metrics` is the 5xx
rates and p99 scraped from Prometheus. The agent does the diagnosis; NavFlow only correlates. One
`query` returns the same facts the baseline gathered across 7–16 separate reads, already
time-ordered.

`sre_metrics` and `sre_logs` are polled by NavFlow's connectors (`prometheus`, `docker_logs`). The
deploy and config signals live behind the platform's admin API, so `run.py` forwards them into the
`sre_deploys` / `sre_config` webhook sources (`POST /ingest/<key>`) right after injecting the fault
— modeling a real deploy/CD webhook. (`sre_alerts` exists as a source but is left out of the view:
its FIRING lines just restate the 5xx rate already in `sre_metrics`.)

### The trigger path

`setup()` defines two triggers on `sre_service_timeline`: `sre_error_spike` (5xx rate > 1.0/s) and
`sre_slow_responses` (p99 > 1000ms). `run.py` subscribes a local webhook to the one that matches the
incident shape, so every incident can wake the agent. When it fires, the daemon POSTs the correlated
timeline and the agent starts from **zero reads** (`WOKEN_PROMPT`). Note the cooldowns (`error_spike`
5m, `slow_responses` 30s): back-to-back runs of the same shape may not re-fire within the window.

## Grading

`found_root_cause(text, incident)` checks whether the agent's diagnosis mentions any of that
incident's `root_hint` keywords (e.g. `latency_regression` → `latency`, `inject_latency_ms`,
`audit`, `slow`). It's a coarse but consistent pass/fail applied identically to every variant.

The deploy "commit messages" are deliberately vague (`"Align resource limits with staging
environment"`, not `"set db_pool_size=1"`) so the agent has to *correlate* the deploy with the
symptoms and timing rather than read the answer off a config diff. That the NavFlow agent still
names the right deploy is the signal the correlation is doing real work — and because the agents are
byte-for-byte identical except for the tools they're handed, the read-count delta is the read path,
nothing else.
