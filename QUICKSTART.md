# Quickstart

Run the **AI SRE incident-response** cookbook end to end against a real, local Tares.

**What it shows:** the same incident-response agent investigates production faults two ways — the
provider-style way (each signal its own tool, fan out across them) and the Tares way (one `query`
returns every signal already correlated). Same agent, same prompt, same answer — only the read path
changes, and you see the tool-call and cost difference on a real run.

## 1. Install and run Tares (the product)

Tares is the data plane the cookbook reads through — it ingests the demo system continuously and
serves the agent one correlated timeline over MCP.

```bash
uv tool install tares            # or: pipx install tares

tares up                         # shell A: daemon + console → http://127.0.0.1:8787
tares mcp                        # shell B: agent MCP endpoint → http://127.0.0.1:8788/mcp
```

Leave both running. (Docs: <https://docs.glassflow.ai/tares>.)

## 2. Bring up the cookbook's stack

Each cookbook ships its own system for Tares to ingest. For this one it's an api-server with
injectable faults, Prometheus, and traffic:

```bash
cd cookbooks/01_sre_incident_response
cd platform && docker compose up -d && cd ..     # pulls the pre-built api-server image
```

> Want to modify the fault-injection app? Build it locally instead:
> `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`

## 3. Install the cookbook and add your API key

```bash
# from the repo root
uv venv && uv pip install -e . && source .venv/bin/activate
#   (activation is per-terminal; in a new shell re-run `source .venv/bin/activate`,
#    or prefix commands with `uv run`, e.g. `uv run python run.py …`)

# the agent runs are real API calls billed to your ANTHROPIC_API_KEY
echo "ANTHROPIC_API_KEY=sk-ant-..." > cookbooks/01_sre_incident_response/.env
```

## 4. Run it

```bash
cd cookbooks/01_sre_incident_response

# one incident, all three variants (baseline fan-out → Tares query → Tares trigger):
python run.py latency_regression
#   incidents: db_pool_exhaustion | latency_regression | error_spike | dependency_outage

# or the full benchmark — all four incidents, baseline vs Tares, with a results table:
python report.py
```

On each run, `run.py` creates the cookbook's own **namespaced** Tares objects (`sre_*` sources, a
correlated view, and triggers) via the daemon's API — it never touches your existing sources —
injects the fault, forwards the platform's deploy/config into Tares, runs the agents, and resets.
Every agent read and trigger dispatch lands in the console at <http://127.0.0.1:8787> → **Agents**.
The agents stream what they're doing live, so you can watch each tool call as it happens.

> Model: default `claude-opus-4-8` (slow, ~1 min/agent). Override with `TARES_MODEL` — e.g.
> `TARES_MODEL=claude-haiku-4-5-20251001 python run.py latency_regression` finishes each agent in
> seconds. The **read-count contrast is identical regardless of model**; only the prose gets terser.

## What a run looks like

```
$ python run.py latency_regression
Tares ready at http://127.0.0.1:8787: created 5 sources, view 'sre_service_timeline', triggers [...] (namespace 'sre_')
Incident: latency_regression  →  inject {'lever': 'inject_latency_ms', 'value': 800}   (expected trigger: sre_slow_responses)
injected the fault; forwarded the deploy + config into Tares.
waiting for the 'sre_slow_responses' push (≤90s) — it also shows in the console → Agents…
  ✓ push arrived after 52.1s (kind=sre_slow_responses)

→ baseline (fan-out): investigating (model=claude-opus-4-8)…
    [   2s] read #1  get_service_health()
    [   9s] read #2  get_logs()
    … (fans out across the systems)
→ tares (one read): investigating (model=claude-opus-4-8)…
    [   3s] read #1  query(view=sre_service_timeline, key=api-server, window=15m)

══════════════════════════════════════════════════════════════════
  SCOREBOARD · latency_regression
══════════════════════════════════════════════════════════════════
  baseline (fan-out)    12 reads across 5 tools   turns=14  $0.55
  tares  (one read)    1 read                    turns=3   $0.15
  tares  (triggered)   0 reads (woken by push)   turns=1   $0.12

  → Tares collapsed the read path 12× (12 → 1) and reached the same root cause.

  WHAT TARES SERVED (the single read the agent made):
    [T-40s] [sre_deploys] deploy b807f6e8 by bob — Add synchronous audit-log write to user lookup
    [T-40s] [sre_config]  api-server config: db_pool_size=20, db_pool_timeout=2.0
    [T-1s]  [sre_metrics] p99 user-svc=2385ms  ·  5xx rate climbing
    …

  verdict: all agents identified latency regression from the synchronous audit-log deploy  ✓
══════════════════════════════════════════════════════════════════
```

The output leads with **what Tares did** — collapse the read path to one correlated read — not the
agent's prose. Same incident, same answer; only the read path changes (and drops to *zero* when the
trigger wakes the agent with the timeline already attached).

## Teardown

```bash
python run.py teardown                       # remove the cookbook's sre_* objects from Tares
cd cookbooks/01_sre_incident_response/platform && docker compose down   # stop the cookbook stack
# stop tares up / tares mcp with Ctrl-C in their shells
```

For how the pieces fit together (the catalog, the sources, the trigger push, the grading), see
[`cookbooks/01_sre_incident_response/README.md`](cookbooks/01_sre_incident_response/README.md).
