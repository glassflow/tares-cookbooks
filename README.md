# NavFlow Cookbooks

Hands-on, outcome-driven tutorials for [**NavFlow**](https://www.navflow.ai) — the open-source
data plane for AI agents. Each cookbook is a self-contained example you run against a **real,
local NavFlow deployment**: stand up a small system, point NavFlow at it, connect an agent over
MCP, and measure the outcome.

These are companions to the running product, not a simulation. You bring up `navflow up` and
`navflow mcp` locally (below), and each cookbook drives them end to end.

> **New here? → [QUICKSTART.md](QUICKSTART.md)** — install NavFlow, run the first cookbook, and
> read the result in a few minutes.

## Prerequisites (shared by every cookbook)

- **NavFlow**, installed and running locally — the data plane the cookbooks read through:
  ```bash
  uv tool install navflow      # or: pipx install navflow
  navflow up                   # daemon + console → http://127.0.0.1:8787
  navflow mcp                  # agent endpoint → http://127.0.0.1:8788/mcp   (second shell)
  ```
- **Docker** (Desktop running) — each cookbook ships its own stack for NavFlow to ingest.
- **[uv](https://docs.astral.sh/uv/)** (or Python 3.11 / 3.12) — to install the cookbook deps.
- **An Anthropic API key** — the agent runs are real API calls (default model `claude-opus-4-8`).

See the [NavFlow docs](https://www.navflow.ai/docs) for install, concepts, connectors, and MCP setup.

## Cookbooks

| # | Cookbook | Outcome it measures |
|---|---|---|
| 01 | [**AI SRE — incident response**](cookbooks/01_sre_incident_response/) | Same incident-response agent, same four production faults, same answers — **NavFlow collapses the per-system tool fan-out into one correlated read.** Measured in tool calls, turns, and real API cost. |

More to come. Each is standalone and ships its own stack.

## How a cookbook is laid out

Every cookbook is a directory under `cookbooks/` that owns everything it needs — there is no
shared framework to learn:

```
cookbooks/01_sre_incident_response/
  platform/         ← the system this cookbook stands up for NavFlow to ingest (docker compose)
  navflow_client.py ← creates the cookbook's own namespaced NavFlow sources/view/triggers via the API
  *_agent.py        ← the agents under test (a provider-style baseline vs the NavFlow read path)
  run.py            ← run one scenario and print the scoreboard
  report.py         ← run the full benchmark and print the results table
  README.md         ← the walkthrough
```

Different cookbooks may ship completely different stacks — the shape above is a convention, not a
constraint.

Each cookbook is a **guest** on your NavFlow: it creates its own objects under a namespace prefix
(cookbook 01 uses `sre_`), never touches your existing sources, and cleans up after itself
(`python run.py teardown`).

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
