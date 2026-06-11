"""Shared agent-run instrumentation and prompts, reused by run.py and benchmark.py."""
import os
import time

from dotenv import load_dotenv
from claude_agent_sdk import (
    query as run_query, AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
)

load_dotenv()
MODEL = os.getenv("NAVFLOW_MODEL", "claude-opus-4-8")

# Fail closed: require a real API key. We deliberately do NOT let the SDK fall back to Claude Code
# subscription auth, so cost/token numbers reflect actual API billing. A missing key hard-fails here
# rather than silently running on the subscription.
if not os.environ.get("ANTHROPIC_API_KEY"):
    raise SystemExit(
        "ANTHROPIC_API_KEY is not set. Put it in cookbooks/01_sre_incident_response/.env — "
        "refusing to fall back to subscription auth so the reported cost is real API pricing."
    )
# ANTHROPIC_AUTH_TOKEN outranks ANTHROPIC_API_KEY in the SDK's auth precedence; drop it so the
# key we just verified is unambiguously the one used.
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

INCIDENT_PROMPT = """We're getting reports of API errors and timeouts from users.
Something is wrong with the api-server. Investigate thoroughly:
- Check error rates and latency
- Look at DB connections and dependencies
- Check container logs for errors
- Look at the current config and recent deploys for anything that changed
- Identify the root cause

Report your findings but do NOT apply any fixes yet."""

WOKEN_PROMPT = """NavFlow triggered you: a condition fired on api-server. The correlated timeline
is attached below — you did not have to fetch anything. Confirm the root cause and recommend the fix.

--- NavFlow trigger payload ---
{payload}
--- end payload ---
"""


async def run_agent(options, prompt, prefix, read_names) -> dict:
    reads = writes = meta = 0
    final = []
    res = {}
    t0 = time.time()
    async for message in run_query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    final.append(block.text.strip())
                elif isinstance(block, ToolUseBlock):
                    name = block.name.replace(prefix, "")
                    if name == "ToolSearch":
                        meta += 1
                    elif name in read_names:
                        reads += 1
                    else:
                        writes += 1
        elif isinstance(message, ResultMessage):
            res["cost"] = getattr(message, "total_cost_usd", None)
            res["turns"] = getattr(message, "num_turns", None)
            res["usage"] = getattr(message, "usage", None) or {}
    u = res.get("usage", {})
    in_tok = u.get("input_tokens", 0) or 0
    out_tok = u.get("output_tokens", 0) or 0
    cache_r = u.get("cache_read_input_tokens", 0) or 0
    cache_w = u.get("cache_creation_input_tokens", 0) or 0
    return {
        "reads": reads, "writes": writes,
        "cost": res.get("cost") or 0.0, "turns": res.get("turns") or 0,
        "wall": round(time.time() - t0, 1), "text": "\n".join(final),
        "in": in_tok, "out": out_tok, "cache_r": cache_r, "cache_w": cache_w,
        # cache-neutral input: what the input would have cost with no prompt cache at all
        "logical_in": in_tok + cache_r + cache_w,
    }
