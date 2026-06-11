"""Autonomous multi-incident benchmark — navflow-cookbooks platform, NavFlow side backed by the
REAL navflow-mvp service (navflowd).

Each of the 4 faults runs ONCE through the baseline and ONCE through navflow, each with a fresh
per-run nonce so every one of the 8 runs has a COLD prompt cache (no warm carryover). A fresh
navflowd (clean DuckDB) is started per incident so each timeline is isolated. API-billed: harness
fails closed on the key and strips subscription fallback.

    python report.py     # run from cookbooks/01_sre_incident_response; platform + navflowd must be up
"""
import os
import time
import uuid
import asyncio
import subprocess

import httpx
from claude_agent_sdk import ClaudeAgentOptions

import platform_client as pc
from incidents import INCIDENTS, found_root_cause
from harness import run_agent, INCIDENT_PROMPT, MODEL
import baseline_agent
import navflow_agent

NAVFLOWD_DIR = "/Users/ashishbagri/WorkData/source/github/navflow/navflow-mvp"
NAVFLOWD_BIN = os.path.join(NAVFLOWD_DIR, ".venv/bin/navflowd")
NAVFLOWD_URL = "http://127.0.0.1:8787"
SETTLE = 35  # seconds after inject before snapshotting, so symptoms register


def sh(cmd):
    subprocess.run(cmd, shell=True, capture_output=True)


def baseline_options(nonce):
    return ClaudeAgentOptions(
        system_prompt=baseline_agent.SYSTEM_PROMPT + f"\n\n[run-id: {nonce}]",
        mcp_servers={"sre": baseline_agent.baseline_server},
        allowed_tools=[f"mcp__sre__{t}" for t in baseline_agent.READ_TOOLS],
        permission_mode="acceptEdits", model=MODEL)


def navflow_options(nonce):
    return ClaudeAgentOptions(
        system_prompt=navflow_agent.SYSTEM_PROMPT + f"\n\n[run-id: {nonce}]",
        mcp_servers={"navflow": navflow_agent.navflow_server},
        allowed_tools=["mcp__navflow__query"],
        permission_mode="acceptEdits", model=MODEL)


def restart_navflowd():
    sh("lsof -ti:8787 | xargs kill 2>/dev/null")
    time.sleep(1)
    for f in ("navflow.duckdb", "navflow.duckdb.wal"):
        try:
            os.remove(os.path.join(NAVFLOWD_DIR, f))
        except FileNotFoundError:
            pass
    env = {**os.environ, "NAVFLOW_CATALOG": "catalog-platform.yaml"}
    logf = open("/tmp/navflowd-bench.log", "a")
    return subprocess.Popen([NAVFLOWD_BIN], cwd=NAVFLOWD_DIR, env=env, stdout=logf, stderr=logf)


async def navflowd_ready():
    for _ in range(45):
        try:
            async with httpx.AsyncClient(timeout=5) as cx:
                r = await cx.post(f"{NAVFLOWD_URL}/query",
                                  json={"view": "service_timeline", "key": "api-server", "window": "15m"})
            if "db_pool_size" in r.json().get("payload", ""):
                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def platform_healthy():
    for _ in range(30):
        try:
            async with httpx.AsyncClient(timeout=5) as cx:
                if (await cx.get("http://localhost:8080/health")).status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


async def main():
    if not await platform_healthy():
        print("platform not healthy on :8080 — bring up navflow-cookbooks/platform first.", flush=True)
        return

    rows = []
    for inc in INCIDENTS:
        name = inc["name"]
        print(f"\n========== {name}  ·  inject {inc['fault']} ==========", flush=True)
        await pc.reset()
        await asyncio.sleep(3)
        await pc.inject(**inc["fault"])
        print(f"  injected; waiting {SETTLE}s for symptoms to register...", flush=True)
        await asyncio.sleep(SETTLE)

        restart_navflowd()
        if not await navflowd_ready():
            print("  navflowd did not become ready — skipping incident.", flush=True)
            continue
        await asyncio.sleep(10)  # let config (10s poll) + a few metric/log ticks land

        b = n = None
        try:
            b = await run_agent(baseline_options(uuid.uuid4().hex), INCIDENT_PROMPT,
                                "mcp__sre__", baseline_agent.READ_TOOLS)
            b["root"] = found_root_cause(b["text"], inc)
            print(f"  baseline  reads={b['reads']} turns={b['turns']} cost=${b['cost']:.4f} "
                  f"{b['wall']}s root={'YES' if b['root'] else 'no'}", flush=True)
        except Exception as e:
            print(f"  baseline FAILED: {e}", flush=True)
        try:
            n = await run_agent(navflow_options(uuid.uuid4().hex), INCIDENT_PROMPT,
                                "mcp__navflow__", {"query"})
            n["root"] = found_root_cause(n["text"], inc)
            print(f"  navflow   reads={n['reads']} turns={n['turns']} cost=${n['cost']:.4f} "
                  f"{n['wall']}s root={'YES' if n['root'] else 'no'}", flush=True)
        except Exception as e:
            print(f"  navflow FAILED: {e}", flush=True)

        if b and n:
            rows.append((name, b, n))

    # teardown
    sh("lsof -ti:8787 | xargs kill 2>/dev/null")
    await pc.reset()

    # consolidated table
    print("\n\n============ RESULTS · single cold run each · API-billed · navflow via navflow-mvp ============", flush=True)
    h = f"{'incident':<20} {'agent':<9} {'reads':>5} {'turns':>5} {'wall':>6} {'cache_r':>8} {'cost$':>8} {'root':>5}"
    print(h)
    print("-" * len(h))
    for name, b, n in rows:
        for tag, r in (("baseline", b), ("navflow", n)):
            print(f"{name:<20} {tag:<9} {r['reads']:>5} {r['turns']:>5} {r['wall']:>5}s "
                  f"{r['cache_r']:>8} ${r['cost']:>7.4f} {'YES' if r['root'] else 'no':>5}")
    if rows:
        tb = {"reads": 0, "turns": 0, "cost": 0.0}
        tn = {"reads": 0, "turns": 0, "cost": 0.0}
        for _, b, n in rows:
            for k in tb:
                tb[k] += b[k]
                tn[k] += n[k]
        print("-" * len(h))
        print(f"{'TOTAL':<20} {'baseline':<9} {tb['reads']:>5} {tb['turns']:>5}")
        print(f"{'TOTAL':<20} {'navflow':<9} {tn['reads']:>5} {tn['turns']:>5}")

        def ratio(a, c):
            return f"{a / c:.1f}x" if c else "—"
        print(f"\nbaseline / navflow — reads {ratio(tb['reads'], tn['reads'])}, "
              f"turns {ratio(tb['turns'], tn['turns'])}, cost {ratio(tb['cost'], tn['cost'])} "
              f"(baseline ${tb['cost']:.2f} vs navflow ${tn['cost']:.2f})")
    print("\n(cost/cache single-cold-run, cache-sensitive; reads & turns are the stable axes.)")
    print("DONE.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
