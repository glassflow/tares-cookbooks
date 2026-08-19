# Tares Cookbooks

Hands-on, outcome-driven tutorials for [**Tares**](https://github.com/glassflow/tares) — the open-source
data plane for AI agents. Each cookbook is a self-contained example you run against a **real,
local Tares deployment**: stand up a small system, point Tares at it, connect an agent over
MCP, and measure the outcome.

These are companions to the running product, not a simulation. You bring up `tares up` and
`tares mcp` locally (below), and each cookbook drives them end to end.

> **New here? → [QUICKSTART.md](QUICKSTART.md)** — install Tares, run the first cookbook, and
> read the result in a few minutes.

## Prerequisites (shared by every cookbook)

- **Tares**, installed and running locally — the data plane the cookbooks read through:
  ```bash
  uv tool install tares      # or: pipx install tares
  tares up                   # daemon + console → http://127.0.0.1:8787
  tares mcp                  # agent endpoint → http://127.0.0.1:8788/mcp   (second shell)
  ```
- **Docker** (Desktop running) — each cookbook ships its own stack for Tares to ingest.
- **[uv](https://docs.astral.sh/uv/)** (or Python 3.11 / 3.12) — to install the cookbook deps.
- **An Anthropic API key** — the agent runs are real API calls (default model `claude-opus-4-8`).

See the [Tares docs](https://docs.glassflow.ai/tares) for install, concepts, connectors, and MCP setup.

## Cookbooks

| # | Cookbook | Outcome it measures |
|---|---|---|
| 01 | [**AI SRE — incident response**](cookbooks/01_sre_incident_response/) | Same incident-response agent, same four production faults, same answers — **Tares collapses the per-system tool fan-out into one correlated read.** Measured in tool calls, turns, and real API cost. |
| 02 | [**Shared code context**](cookbooks/02_shared_context/) | Two sample services, one context repo, three real changes: **the context repo stays current on its own**, one pull request per change, measured in time from commit to PR. Uses the Shared code context use case (Tares 1.8.0+). |

More to come. Each is standalone and ships its own stack.

## How a cookbook is laid out

Every cookbook is a directory under `cookbooks/` that owns everything it needs — there is no
shared framework to learn:

```
cookbooks/01_sre_incident_response/
  platform/         ← the system this cookbook stands up for Tares to ingest (docker compose)
  tares_client.py ← creates the cookbook's own namespaced Tares sources/view/triggers via the API
  *_agent.py        ← the agents under test (a provider-style baseline vs the Tares read path)
  run.py            ← run one scenario and print the scoreboard
  report.py         ← run the full benchmark and print the results table
  README.md         ← the walkthrough
```

Different cookbooks may ship completely different stacks — the shape above is a convention, not a
constraint.

Each cookbook is a **guest** on your Tares: it creates its own objects under a namespace prefix
(cookbook 01 uses `sre_`), never touches your existing sources, and cleans up after itself
(`python run.py teardown`).

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
