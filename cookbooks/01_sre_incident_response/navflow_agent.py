"""The NavFlow read path: the same SRE task as the baseline, but the fan-out tools are replaced by
ONE correlated read — served by the real running product over MCP.

The point of moving off the Claude Code harness (approach B): we open our own MCP client session to
`navflow mcp`, discover its tools, and register only the one(s) we want. So even though the server
advertises 13 tools, the model's context carries exactly `query` (one schema) — not the full surface.

`mcp_tools()` yields the wrapped runnable tools; the MCP session stays open for the duration of the
`async with`, so run.py opens it once and runs every NavFlow variant inside it.
"""
import os
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from anthropic.lib.tools.mcp import async_mcp_tool

from navflow_client import VIEW, KEY

NAVFLOW_MCP_URL = os.getenv("NAVFLOW_MCP_URL", "http://127.0.0.1:8788/mcp")

# Tool names that GATHER context — counted as reads. (We only expose `query`, but keep the set broad.)
READ_TOOLS = {"query", "read", "catalog_list", "catalog_describe", "list_sources", "list_connectors"}

SYSTEM_PROMPT = f"""You are an expert SRE incident response bot backed by NavFlow, a data plane that
continuously ingests everything happening to the system and serves it correlated.

You have ONE data tool:
- query(view, key, window): ONE time-ordered timeline of everything that happened to a service —
  metrics, logs, deploys, config — already merged. Call it exactly once as
  query(view="{VIEW}", key="{KEY}", window="15m") and pass NO other arguments. Read the unified
  timeline, trace the causal chain from the symptoms back to the root cause, and explain your
  reasoning. Only call query again if the single timeline genuinely lacks something.

Report your findings and name the root cause. Do NOT apply any fixes."""

REMEMBER_SYSTEM_PROMPT = f"""You are the same NavFlow-backed SRE agent. You have already diagnosed the
incident. Record your conclusion so it lands in future timelines: call
remember(key="{KEY}", content="<one line: root cause + the evidence that proves it>") exactly once,
then reply "recorded". Do not call any other tool."""


@asynccontextmanager
async def mcp_tools():
    """Open an MCP session to `navflow mcp`, discover its tools, and hand back only the ones we
    register with the model — {'query': ..., 'remember': ...}. Everything else the server exposes
    stays out of the model's context."""
    async with streamablehttp_client(NAVFLOW_MCP_URL) as (read_s, write_s, _):
        async with ClientSession(read_s, write_s) as session:
            await session.initialize()
            available = {t.name: t for t in (await session.list_tools()).tools}
            missing = {"query"} - available.keys()
            if missing:
                raise SystemExit(f"navflow mcp is up but missing tools {sorted(missing)}. "
                                 f"Is the daemon seeded? (run.py calls navflow_client.setup())")
            wrapped = {name: async_mcp_tool(available[name], session)
                       for name in ("query", "remember") if name in available}
            yield wrapped
