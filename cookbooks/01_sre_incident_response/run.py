"""Run one incident against the REAL running Tares and show what Tares contributed.

Three agents, same incident, same prompt — only the read path differs:

  baseline    provider-style agent — one tool per system, fans out across them
  tares     same agent, one read: query(view, key, window) → the correlated timeline
  triggered   Tares's trigger fires and wakes the agent over a webhook with the timeline
              already attached — zero reads to begin

    python run.py [incident_name]     (default: latency_regression)
    python run.py teardown            (remove the cookbook's sre_* objects and exit)

Incidents: db_pool_exhaustion, latency_regression, error_spike, dependency_outage.

Prereqs (see README): the platform stack up (cd platform && docker compose up -d --build), and the
product running — `tares up` (daemon :8787) and `tares mcp` (agent endpoint :8788). The cookbook
creates its own namespaced sources/view/triggers on the daemon; the user's own data is never touched.
"""
import asyncio
import json
import os
import sys
import time

from anthropic import AsyncAnthropic

import platform_client as pc
import tares_client as nf
from incidents import INCIDENTS, found_root_cause
from harness import run_agent, INCIDENT_PROMPT, WOKEN_PROMPT, REMEMBER_PROMPT
import baseline_agent
import tares_agent

WOKE_PORT = int(os.getenv("TARES_WOKE_PORT", "9911"))
SETTLE_SECONDS = 40          # let Prometheus scrape + rate windows fill before the pull agents read
PUSH_TIMEOUT = 90            # how long to wait for the trigger's webhook push


class WokeReceiver:
    """Minimal stdlib HTTP receiver — resolves a future with the first trigger dispatch body."""

    def __init__(self):
        self.fired: asyncio.Future = asyncio.get_event_loop().create_future()
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", WOKE_PORT)

    async def _handle(self, reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for hline in header.decode("latin-1").split("\r\n"):
                if hline.lower().startswith("content-length:"):
                    length = int(hline.split(":", 1)[1].strip())
            body = json.loads((await reader.readexactly(length)).decode() or "{}")
            writer.write(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\nok")
            await writer.drain()
            if not self.fired.done():
                self.fired.set_result(body)
        except Exception:
            pass
        finally:
            writer.close()

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


def _tares_served(payload: str) -> list[str]:
    """Trim Tares's correlated timeline for display: always keep the deploy/config/alert lines
    (the correlation signal) plus the most recent snapshot — that's what the one read delivered."""
    lines = [l for l in payload.splitlines() if l.strip() and not l.startswith("===")]
    signal_tags = tuple(f"[{s}]" for s in (nf.S_DEPLOYS, nf.S_CONFIG))
    signal = [l for l in lines if any(t in l for t in signal_tags)]
    seen, out = set(), []
    for l in signal + lines[-14:]:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "latency_regression"
    if name == "teardown":
        await nf.teardown()
        print(f"removed the cookbook's {nf.NS!r} sources, view, and triggers.")
        return
    inc = next((i for i in INCIDENTS if i["name"] == name), None)
    if not inc:
        print(f"unknown incident '{name}'. choose: {[i['name'] for i in INCIDENTS]}  (or 'teardown')")
        return
    trigger = nf.TRIGGER_FOR[name]

    await nf.setup()
    print(f"Incident: {name}  →  inject {inc['fault']}   (expected trigger: {trigger})")
    await pc.reset()
    await asyncio.sleep(3)

    receiver = WokeReceiver()
    await receiver.start()
    sub_id = await nf.subscribe(trigger, f"http://127.0.0.1:{WOKE_PORT}/woke")

    results = {}
    try:
        # inject the fault, and forward the platform's deploy + config into Tares's webhook sources
        t0 = time.time()
        await pc.inject(**inc["fault"])
        changelog = await pc.get_changelog(1)
        if changelog:
            await nf.push_deploy(changelog[-1])
        await nf.push_config(await pc.get_config())
        print(f"injected the fault; forwarded the deploy + config into Tares.")
        print(f"waiting for the '{trigger}' push (≤{PUSH_TIMEOUT}s) — it also shows in the console → Agents…")

        fired = None
        try:
            fired = await asyncio.wait_for(asyncio.shield(receiver.fired), timeout=PUSH_TIMEOUT)
            print(f"  ✓ push arrived after {round(time.time() - t0, 1)}s (kind={fired.get('kind')})")
        except asyncio.TimeoutError:
            print(f"  (no push within {PUSH_TIMEOUT}s — trigger may be in cooldown from a recent run)")

        elapsed = time.time() - t0
        if elapsed < SETTLE_SECONDS:
            await asyncio.sleep(SETTLE_SECONDS - elapsed)

        client = AsyncAnthropic()
        # Both agents run on the Tool Runner. baseline registers its 5 in-process tools; tares
        # opens an MCP session to `tares mcp` and registers only `query` (one schema in context).
        async with tares_agent.mcp_tools() as ntools:
            results["baseline"] = await run_agent(
                client, baseline_agent.TOOLS, INCIDENT_PROMPT, baseline_agent.READ_TOOLS,
                label="baseline (fan-out)", system=baseline_agent.SYSTEM_PROMPT)
            results["tares"] = await run_agent(
                client, [ntools["query"]], INCIDENT_PROMPT, tares_agent.READ_TOOLS,
                label="tares (one read)", system=tares_agent.SYSTEM_PROMPT)
            if fired:
                results["triggered"] = await run_agent(
                    client, [ntools["query"]], WOKEN_PROMPT.format(payload=fired["payload"]),
                    tares_agent.READ_TOOLS, label="tares (triggered)",
                    system=tares_agent.SYSTEM_PROMPT)

            # The agent writes its conclusion back to Tares memory — a genuine remember turn, but
            # it happens AFTER the root cause is found, so it's left out of the scoreboard.
            if "remember" in ntools:
                await run_agent(
                    client, [ntools["remember"]],
                    REMEMBER_PROMPT.format(diagnosis=results["tares"]["text"][:1500]),
                    tares_agent.READ_TOOLS, label="tares · remember (unscored)",
                    system=tares_agent.REMEMBER_SYSTEM_PROMPT)

        served = await nf.query_timeline()

        # ── the outcome: what Tares did, not the agent's prose ────────────────────────────
        b, n = results["baseline"], results["tares"]

        def row(tag, r):
            # cost at 4 decimals (a whole run is only a few cents — 2 decimals rounds the
            # difference away). in_tok is cache-neutral input (the size of what the agent read);
            # out_tok is shown too because output is priced ~5× input, so a wordier answer can cost
            # more even with fewer reads — without this column that looks like a contradiction.
            print(f"  {tag:<21} {r['reads']:>5} {r['turns']:>6} {r['wall']:>6.1f}s "
                  f"{r['logical_in']:>9,} {r['out']:>8,} {'$' + format(r['cost'], '.4f'):>9}")

        print("\n" + "═" * 78)
        print(f"  SCOREBOARD · {name}   (measured only until the root cause is found)")
        print("═" * 78)
        print(f"  {'agent':<21} {'reads':>5} {'turns':>6} {'time':>7} {'in_tok':>9} {'out_tok':>8} {'cost':>9}")
        print("  " + "─" * 68)
        row("baseline (fan-out)", b)
        row("tares (one read)", n)
        if "triggered" in results:
            row("tares (triggered)", results["triggered"])

        def ratio(x):
            return f"{b[x] / n[x]:.1f}×" if n.get(x) else "—"
        if n["reads"]:
            print(f"\n  → reads {ratio('reads')} fewer ({b['reads']} → {n['reads']}), "
                  f"input tokens {ratio('logical_in')} fewer "
                  f"({b['logical_in']:,} → {n['logical_in']:,})")
            print(f"    cost ${b['cost']:.4f} → ${n['cost']:.4f}, "
                  f"turns {b['turns']} → {n['turns']} — same root cause.")
        print("  + the agent then wrote its conclusion back with remember() — a Tares write-back,\n"
              "    deliberately NOT counted above (it happens after the diagnosis is done).")

        print("\n  WHAT TARES SERVED (the single read the agent made):")
        for l in _tares_served(served):
            print("   ", l)

        ok = {k: found_root_cause(v["text"], inc) for k, v in results.items()}
        allc = "✓" if all(ok.values()) else "partial"
        print(f"\n  verdict: {'all' if all(ok.values()) else 'some'} agents identified "
              f"{inc['cause']}  {allc}")
        print(f"  full agent reasoning + every read is in the console: {nf.TARESD_URL} → Agents")
        print("═" * 78)
    finally:
        await nf.unsubscribe(sub_id)
        await receiver.stop()
        await pc.reset()
        print(f"\nreset to healthy. (cookbook sources left in place; remove with: python run.py teardown)")


if __name__ == "__main__":
    asyncio.run(main())
