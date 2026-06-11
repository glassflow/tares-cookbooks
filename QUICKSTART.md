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

# 3. create the venv, install the cookbook + SDK, and ACTIVATE the venv
uv venv && uv pip install -e . && source .venv/bin/activate
#   (activation is per-terminal. In a new shell, re-run `source .venv/bin/activate`,
#    or just prefix the run commands below with `uv run`, e.g. `uv run python run.py …`.)

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

# cheaper: use Sonnet instead of the default Opus 4.8 (set NAVFLOW_MODEL)
NAVFLOW_MODEL=claude-sonnet-4-6 python run.py latency_regression
```

> If `python run.py` reports a missing module, your venv isn't active — run
> `source .venv/bin/activate` from the repo root, or use `uv run python run.py …`.

`run.py` takes ~2–3 min (it injects the fault, waits ~30s for symptoms to register, runs the agents,
and resets). `report.py` runs all four, ~10–15 min. Everything resets to healthy on exit.

> Model: the default is `claude-opus-4-8`. Override it with `NAVFLOW_MODEL` (e.g.
> `claude-sonnet-4-6`, or `claude-haiku-4-5-20251001` for the cheapest). The **read-count contrast is
> identical regardless of model** — only the diagnosis prose gets terser — so a cheaper model is fine
> for a quick look.

## What a run looks like

```
$ python run.py latency_regression
Incident: latency_regression  →  inject {'lever': 'inject_latency_ms', 'value': 800}
waiting 30s for symptoms to register...

results:
  baseline (fan-out)     reads=10  turns=12  cost=$0.56  46.4s  root_cause=YES
  navflow (one query)    reads=1   turns=3   cost=$0.15  37.2s  root_cause=YES
```

Same incident, same answer — **10 reads → 1, 12 turns → 3**, both found the root cause. `run.py`
then prints the NavFlow agent's full diagnosis — worth reading to confirm it actually identified the
cause by **correlating the symptoms with the vague deploy** (the config no longer names the fault;
see *Why the result is trustworthy*, below).

> For the error-storm incidents (`error_spike`, `dependency_outage`) you'll also see a third line,
> `navflow (triggered)  reads=0  turns=1` — NavFlow's push path wakes the agent with the timeline
> already attached, so it starts at **zero reads**. (Timeout-shaped faults like latency don't trip the
> 5xx-spike trigger.)

## How to measure the difference

Every run prints that scoreboard. Here's what each column means:

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
