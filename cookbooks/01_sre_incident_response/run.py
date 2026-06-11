"""Run one incident through all three: baseline fan-out, NavFlow query, NavFlow trigger.

    python run.py [incident_name]   (default: latency_regression)

Incidents: db_pool_exhaustion, latency_regression, error_spike, dependency_outage.
The platform stack must be running (cd ../../platform && docker compose up -d).
"""
import sys
import asyncio

import platform_client as pc
from incidents import INCIDENTS, found_root_cause
from harness import run_agent, INCIDENT_PROMPT, WOKEN_PROMPT
import baseline_agent
import navflow_agent


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "latency_regression"
    inc = next((i for i in INCIDENTS if i["name"] == name), None)
    if not inc:
        print(f"unknown incident '{name}'. choose: {[i['name'] for i in INCIDENTS]}")
        return

    print(f"Incident: {name}  →  inject {inc['fault']}")
    await pc.reset()
    await asyncio.sleep(3)
    await pc.inject(**inc["fault"])
    print("waiting 30s for symptoms to register...")
    await asyncio.sleep(30)

    def line(tag, r):
        ok = "YES" if found_root_cause(r["text"], inc) else "no"
        print(f"  {tag:<22} reads={r['reads']}  turns={r['turns']}  "
              f"cost=${r['cost']:.2f}  {r['wall']}s  root_cause={ok}")

    print("\nresults:")
    b = await run_agent(baseline_agent.options, INCIDENT_PROMPT, "mcp__sre__", baseline_agent.READ_TOOLS)
    line("baseline (fan-out)", b)

    n = await run_agent(navflow_agent.options, INCIDENT_PROMPT, "mcp__navflow__", {"query"})
    line("navflow (one query)", n)

    fired = await navflow_agent.trigger.wait(timeout=10)
    if fired:
        t = await run_agent(navflow_agent.options, WOKEN_PROMPT.format(payload=fired["payload"]),
                            "mcp__navflow__", {"query"})
        print(f"  {'navflow (triggered)':<22} fired_after={fired['fired_after']}s  "
              f"reads={t['reads']}  turns={t['turns']}  cost=${t['cost']:.2f}  {t['wall']}s  "
              f"root_cause={'YES' if found_root_cause(t['text'], inc) else 'no'}")

    await pc.reset()
    print("\nreset to healthy.")
    print("\n--- navflow diagnosis (tail) ---\n" + n["text"][-900:])


if __name__ == "__main__":
    asyncio.run(main())
