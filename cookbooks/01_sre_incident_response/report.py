"""Run all four incidents through the baseline and NavFlow agents, one run each, and print a
consolidated metrics table: reads, turns, wall-clock, tokens (incl. cache breakdown), cost, accuracy.

    python report.py

Runs against the REAL running NavFlow (see run.py / README for prereqs): the platform stack up,
plus `navflow up` (daemon :8787) and `navflow mcp` (agent endpoint :8788). `setup()` creates the
cookbook's own namespaced sources/view/triggers on the daemon (never touching the user's data).
Auth: requires ANTHROPIC_API_KEY (the harness fails closed — no subscription fallback), so
cost/tokens are real API billing.

This is the outcome the cookbook measures: same agent, same incidents, same answers — only the read
path changes. NavFlow collapses the baseline's per-system fan-out into a single correlated read.
"""
import asyncio

from anthropic import AsyncAnthropic

import platform_client as pc
import navflow_client as nf
from incidents import INCIDENTS, found_root_cause
from harness import run_agent, INCIDENT_PROMPT
import baseline_agent
import navflow_agent

SETTLE_SECONDS = 40


async def main():
    await nf.setup()
    client = AsyncAnthropic()
    rows = []
    async with navflow_agent.mcp_tools() as ntools:      # one MCP session for the whole run
        for inc in INCIDENTS:
            name = inc["name"]
            print(f"\n=== {name}  →  inject {inc['fault']} ===", flush=True)
            await pc.reset()
            await asyncio.sleep(3)
            await pc.inject(**inc["fault"])
            changelog = await pc.get_changelog(1)
            if changelog:
                await nf.push_deploy(changelog[-1])
            await nf.push_config(await pc.get_config())
            print(f"  waiting {SETTLE_SECONDS}s for symptoms to register...", flush=True)
            await asyncio.sleep(SETTLE_SECONDS)

            b = await run_agent(client, baseline_agent.TOOLS, INCIDENT_PROMPT,
                                baseline_agent.READ_TOOLS, label=f"{name} · baseline",
                                system=baseline_agent.SYSTEM_PROMPT)
            b["root_cause"] = found_root_cause(b["text"], inc)
            print(f"  baseline  reads={b['reads']} turns={b['turns']} {b['wall']}s "
                  f"cost=${b['cost']:.4f} root_cause={'YES' if b['root_cause'] else 'no'}", flush=True)
            n = await run_agent(client, [ntools["query"]], INCIDENT_PROMPT,
                                navflow_agent.READ_TOOLS, label=f"{name} · navflow",
                                system=navflow_agent.SYSTEM_PROMPT)
            n["root_cause"] = found_root_cause(n["text"], inc)
            print(f"  navflow   reads={n['reads']} turns={n['turns']} {n['wall']}s "
                  f"cost=${n['cost']:.4f} root_cause={'YES' if n['root_cause'] else 'no'}", flush=True)

            rows.append((name, "baseline", b))
            rows.append((name, "navflow", n))

    await pc.reset()

    # consolidated table
    print("\n\n================================ RESULTS ================================")
    h = (f"{'incident':<20} {'agent':<9} {'reads':>5} {'turns':>5} {'wall':>6} "
         f"{'in':>7} {'out':>6} {'cache_r':>8} {'logical_in':>11} {'cost$':>8} {'root':>5}")
    print(h)
    print("-" * len(h))
    for name, agent, r in rows:
        print(f"{name:<20} {agent:<9} {r['reads']:>5} {r['turns']:>5} {r['wall']:>5}s "
              f"{r['in']:>7} {r['out']:>6} {r['cache_r']:>8} {r['logical_in']:>11} "
              f"${r['cost']:>7.4f} {'YES' if r['root_cause'] else 'no':>5}")

    # totals + ratios
    tot = {}
    for _, agent, r in rows:
        t = tot.setdefault(agent, {"reads": 0, "turns": 0, "cost": 0.0, "logical_in": 0, "out": 0})
        for k in t:
            t[k] += r[k]
    print("-" * len(h))
    for agent in ("baseline", "navflow"):
        t = tot[agent]
        print(f"{'TOTAL':<20} {agent:<9} {t['reads']:>5} {t['turns']:>5} {'':>6} "
              f"{'':>7} {t['out']:>6} {'':>8} {t['logical_in']:>11} ${t['cost']:>7.4f}")
    b, n = tot["baseline"], tot["navflow"]

    def ratio(x):
        return f"{b[x] / n[x]:.1f}x" if n[x] else "—"
    print(f"\nbaseline / navflow  —  reads {ratio('reads')}, turns {ratio('turns')}, "
          f"cost {ratio('cost')}, logical input tokens {ratio('logical_in')}")
    print("(logical_in = input + cache_read + cache_create — cache-neutral; cost is real API pricing)")


if __name__ == "__main__":
    asyncio.run(main())
