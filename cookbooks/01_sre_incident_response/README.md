# 01 · SRE Incident Response

An SRE agent investigates a production incident two ways against the **same running system**:

1. **Baseline** — the provider-style agent: each signal (metrics, logs, config, deploys) is its
   own tool, and the agent fans out across them on every investigation.
2. **NavFlow read path** — the *same* agent and the *same* prompt, but the fan-out tools are
   replaced by a single `query(view, key, window)` that returns those signals already correlated.

The NavFlow side is backed by the real **navflow-mvp** service (`navflowd`, in the sibling
`navflow-mvp` repo): it ingests the platform's signals into DuckDB and serves one correlated
timeline. The baseline and NavFlow agents are byte-for-byte identical except for the tools they're
given — only the read path changes.

Everything runs against the `platform/` demo (FastAPI + Postgres + Prometheus + Grafana), which
stages four distinct faults at runtime.

## What you'll see

`report.py` injects each fault, runs both agents once, and prints this. One cold run per incident
per agent (a fresh nonce forces a cold prompt cache so runs don't flatter each other), on a real
Anthropic API key — so cost is actual billing.

| incident | baseline reads / turns | navflow reads / turns | baseline cost | navflow cost | root cause |
|---|---|---|---|---|---|
| db_pool_exhaustion | 7 / 9 | 1 / 3 | $0.51 | $0.13 | ✅ |
| latency_regression | 11 / 13 | 1 / 3 | $0.23 | $0.15 | ✅ |
| error_spike | 9 / 11 | 1 / 3 | $0.23 | $0.14 | ✅ |
| dependency_outage | 8 / 10 | 1 / 3 | $0.21 | $0.16 | ✅ |
| **total** | **35 / 43** | **4 / 12** | **$1.17** | **$0.58** | 8 / 8 |

**Baseline ÷ NavFlow: reads 8.8×, turns 3.6×, cost ~2×.**

The agent reaches the same root cause either way. The NavFlow agent is dead flat at **1 read / 3
turns** on every incident; the baseline swings 7–11 reads depending on how hard the fault is to
disambiguate. That consistency is the finding — the correlated query removes the search variance,
not just the call count.

Honest caveats: **single cold run each**, so treat cost as directional. The db_pool baseline ($0.51)
is a first-run cache outlier (the other three sit near $0.22) — drop it and the cost gap is ~1.5×.
And the token/context axis is *not* a NavFlow win (its one query returns a fat payload), so we lead
with reads and turns.

## Setup

```bash
# 1. the platform (api-server :8080, Prometheus :9090, Grafana :3000)
cd platform && docker compose up -d --build && cd ..

# 2. install the navflow-mvp service (sibling repo) — report.py launches navflowd from here
cd ../navflow-mvp && uv venv && uv pip install -e . && cd ../navflow-cookbooks

# 3. install the cookbook deps
uv venv && uv pip install -e .

# 4. put ANTHROPIC_API_KEY in cookbooks/01_sre_incident_response/.env
#    The harness fails closed if it's missing — it will NOT fall back to subscription auth, so the
#    reported cost is real API billing.
```

## Run

```bash
cd cookbooks/01_sre_incident_response
python report.py
```

`report.py` drives the whole benchmark: for each fault it resets the platform, injects the fault,
waits ~35s for symptoms to register, **starts a fresh `navflowd`** (clean DuckDB, so each incident's
timeline is isolated) ingesting from the platform, then runs the baseline and NavFlow agents once
each with a fresh cold-cache nonce. It prints the consolidated table and tears down at the end.

Incidents: `db_pool_exhaustion`, `latency_regression`, `error_spike`, `dependency_outage`.

## How it works

| file | role |
|---|---|
| `baseline_agent.py` | The provider-style agent: 5 read tools (`get_service_health`, `query_metrics`, `get_logs`, `get_config`, `get_recent_deploys`) + its system prompt. |
| `navflow_agent.py` | The same agent with one tool, `mcp__navflow__query`, which proxies to `navflowd`'s `/query`. |
| `harness.py` | The shared stopwatch + scorer. `run_agent()` runs any agent's options and counts reads / turns / tokens / cost / wall-clock. Holds the shared task prompt; fails closed on the API key. |
| `incidents.py` | The four incidents (fault lever + value) and `found_root_cause()`, the keyword grader. |
| `platform_client.py` | Thin I/O to the platform — Prometheus queries, the admin config/changelog/fault API. |
| `report.py` | Drives the benchmark: per-incident reset → inject → fresh `navflowd` → run both agents cold → consolidated table. |

### The read path

The whole substitution is one hop, and the data now comes from a real service:

```
agent → mcp__navflow__query   (navflow_agent.py)
                  │  HTTP
                  ▼
        navflowd  POST /query   (navflow-mvp repo)
                  │  keyed + windowed scan over DuckDB, merged + time-ordered
                  ▼
        DuckDB  ←  connectors  ←  Prometheus / docker logs / admin API (the platform)
```

`navflowd` continuously polls the platform's signals (metrics, logs, config, deploys, alerts) into
DuckDB; `query(view=service_timeline, key=api-server, window=15m)` returns them as one correlated
timeline. One `query` returns the same facts the baseline gathered across 7–11 separate reads. The
catalog that maps the platform's signals into NavFlow lives at `navflow-mvp/catalog-platform.yaml`.

### Cold cache

`report.py` appends a unique nonce to each agent's system prompt per run, so every one of the 8 runs
starts with a cold prompt cache — no warm carryover from a prior run. This is why single runs are
comparable; averaging multiple runs would be invalid because runs 2+ hit warm cache.

## Grading

`found_root_cause(text, incident)` checks whether the diagnosis mentions any of that incident's
`root_hint` keywords. Coarse but consistent, applied identically to both agents.

The deploy commit messages are deliberately vague (`"Align resource limits with staging
environment"`, not `"set db_pool_size=1"`) so the agent has to *correlate* the deploy with the
symptoms rather than read the answer off a config diff. That the NavFlow agent still names the right
deploy is the signal the correlation is doing real work.
