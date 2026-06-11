# Quickstart

Run the SRE incident-response cookbook end to end and read the result. Everything runs locally —
no external service.

**What it shows:** the same incident-response agent investigates four production faults two ways —
the provider-style way (each signal its own tool, fan out across them) and the NavFlow way (one
`query` returns all signals already correlated). Same agent, same prompt, same answer — only the
read path changes.

## Prerequisites

- **Docker** (Desktop running) — for the demo system
- **[uv](https://docs.astral.sh/uv/)** (or Python 3.11/3.12) — to install dependencies
- **An Anthropic API key** — the runs are real API calls (default model `claude-opus-4-8`)

## Setup (≈3 minutes)

```bash
# 1. clone
git clone https://github.com/navflow/navflow-cookbooks.git
cd navflow-cookbooks

# 2. bring up the demo system (api-server :8080, Prometheus :9090, Grafana :3000)
cd platform && docker compose up -d --build && cd ..

# 3. install the cookbook + SDK
uv venv && uv pip install -e .

# 4. add your API key (the harness requires it — no subscription fallback, so cost is real)
echo "ANTHROPIC_API_KEY=sk-ant-..." > cookbooks/01_sre_incident_response/.env

# 5. confirm the system is healthy (wait ~30s after step 2 for Prometheus to scrape)
curl -s localhost:8080/health     # -> {"status":"healthy", ...}
```

## Run

```bash
cd cookbooks/01_sre_incident_response

# one incident, all three variants (baseline → NavFlow query → NavFlow trigger):
python run.py latency_regression
#   incidents: db_pool_exhaustion | latency_regression | error_spike | dependency_outage

# or the full benchmark — all four incidents, baseline vs NavFlow, with a results table:
python report.py
```

`run.py` takes ~2–3 min (it injects the fault, waits ~30s for symptoms to register, runs the agents,
and resets). `report.py` runs all four, ~10–15 min. Everything resets to healthy on exit.

> Tip: override the model with `NAVFLOW_MODEL=claude-sonnet-4-6 python run.py …` — the **read count is
> identical regardless of model**, so a cheaper model is fine for a quick look.

## How to measure the difference

Every run prints a scoreboard. This is what to look at:

```
results:
  baseline (fan-out)     reads=11  turns=13  cost=$0.23  44.5s  root_cause=YES
  navflow (one query)    reads=1   turns=3   cost=$0.16  26.3s  root_cause=YES
  navflow (triggered)    fired_after=0.1s  reads=0  turns=1  ...  root_cause=YES
```

| Metric | What it means | What to expect |
|---|---|---|
| **Read calls** | tool calls the agent made to *gather context* | baseline **7–16**, NavFlow **always 1**, triggered **0** — the headline: the read path collapses |
| **Agent turns** | round-trips through the model | baseline **9–18**, NavFlow **always 3** |
| **root_cause** | did it actually find the bug? | **YES on both** — the accuracy floor; NavFlow doesn't trade correctness for fewer calls |
| **Cost** | real API billing | NavFlow lower, but single-run and cache-sensitive — treat as directional, not exact |
| **Wall clock** | end-to-end latency | NavFlow faster, but noisy run-to-run |

**The result that holds up is the *shape*, not any single number:** NavFlow is dead-flat at **1 read /
3 turns** on *every* incident, while the baseline swings 7→16 reads depending on how hard the fault is
to disambiguate. Run `report.py` and the totals make it obvious — roughly **35→4 reads, 43→12 turns
across the four faults**, same root cause every time.

## Why the result is trustworthy (not the agent cheating)

- The deploy commit messages in the changelog are **deliberately vague** — e.g. `"Align resource
  limits with staging environment"`, never `"set db_pool_size=1"`. So the agent has to **correlate**
  the deploy with the symptoms and timing, not read the answer off a config diff. That the NavFlow
  agent still names the right deploy is the proof the correlated read is doing real reasoning, not
  just lowering a counter.
- The baseline and NavFlow agents are **byte-for-byte identical** — same loop, same model, same
  system/task prompts, same grading. The *only* difference is the tools they're handed (five fan-out
  tools vs. one `query`).
- `run.py` prints the NavFlow diagnosis tail, so you can read the actual root-cause reasoning and the
  correlated timeline it worked from.

## Teardown

```bash
cd ../../platform && docker compose down
```

For how the pieces fit together (the in-process data plane, the sources, the grading), see
[`cookbooks/01_sre_incident_response/README.md`](cookbooks/01_sre_incident_response/README.md).
