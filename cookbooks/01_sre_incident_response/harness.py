"""Shared agent-run instrumentation and prompts, reused by run.py and report.py.

Both agents run on the plain Anthropic SDK's Tool Runner (`client.beta.messages.tool_runner`),
NOT the Claude Agent SDK / Claude Code CLI. That means WE build the `tools` list, so each agent
carries EXACTLY the tool schemas we register — the baseline its 5 fan-out tools, NavFlow its single
`query`. No harness-inherited surface, no CLI framing floor, no settings/plugins leaking in.

Cost: the raw Messages API returns token `usage`, not dollars (unlike the Claude Code CLI's
`total_cost_usd`). So we compute cost from usage × MODEL_PRICING — identically for both agents,
which is what keeps the comparison honest.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
MODEL = os.getenv("NAVFLOW_MODEL", "claude-opus-4-8")
MAX_TOKENS = int(os.getenv("NAVFLOW_MAX_TOKENS", "4096"))

# Fail closed: require a real API key so cost/token numbers reflect actual API billing.
if not os.environ.get("ANTHROPIC_API_KEY"):
    raise SystemExit(
        "ANTHROPIC_API_KEY is not set. Put it in cookbooks/01_sre_incident_response/.env — "
        "the runs are real API calls, so the reported cost is real API pricing."
    )
# ANTHROPIC_AUTH_TOKEN outranks ANTHROPIC_API_KEY in the SDK's auth precedence; drop it so the
# key we just verified is unambiguously the one used.
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# Published $/1M tokens (input, output). cache-read ≈ 0.1× input, cache-write(5m) ≈ 1.25× input.
# Used to turn token usage into dollars (the Messages API returns tokens, not cost). Approximate —
# the read/turn/token counts are the hard metrics; cost is directional.
MODEL_PRICING = {
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-opus-4-6":   (5.0, 25.0),
    "claude-sonnet-5":   (2.0, 10.0),   # intro pricing through 2026-08-31 (standard 3/15)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
    "claude-fable-5":    (10.0, 50.0),
}


def _price(model: str):
    for k, v in MODEL_PRICING.items():
        if model.startswith(k):
            return v
    return (5.0, 25.0)   # default to Opus-tier if unknown


def _cost(model: str, in_tok: int, out_tok: int, cache_r: int, cache_w: int) -> float:
    inp, outp = _price(model)
    return (in_tok * inp + cache_r * inp * 0.1 + cache_w * inp * 1.25 + out_tok * outp) / 1_000_000


INCIDENT_PROMPT = """We're getting reports of API errors and timeouts from users.
Something is wrong with the api-server. Investigate thoroughly:
- Check error rates and latency
- Look at DB connections and dependencies
- Check container logs for errors
- Look at the current config and recent deploys for anything that changed
- Identify the root cause

Report your findings but do NOT apply any fixes yet."""

WOKEN_PROMPT = """NavFlow triggered you: a condition fired on api-server. The correlated timeline
is attached below — you did not have to fetch anything. Confirm the root cause.
Report your findings but do NOT apply any fixes.

--- NavFlow trigger payload ---
{payload}
--- end payload ---
"""

# Used for the UNSCORED write-back turn (not part of the read/cost/latency measurement).
REMEMBER_PROMPT = """This is the incident you just diagnosed:

{diagnosis}

Record your conclusion now."""


def _fmt_args(args: dict) -> str:
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        s = str(v)
        parts.append(f"{k}={s[:40] + '…' if len(s) > 40 else s}")
    return ", ".join(parts)


async def run_agent(client, tools, prompt, read_names, label: str = "", live: bool = True,
                    system: str = "") -> dict:
    """Run one agent to completion via the Tool Runner and return the metrics dict.

    `tools` is the exact list of runnable tools this agent may use (that's the whole point of moving
    off the CLI — we control the surface). `read_names` are the tool names that count as context
    reads. Live-streams each tool call. Cost is computed from summed token usage × MODEL_PRICING.
    """
    reads = writes = turns = 0
    read_tools: set[str] = set()
    final: list[str] = []
    tot = {"input_tokens": 0, "output_tokens": 0,
           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    t0 = time.time()
    if live and label:
        print(f"\n→ {label}: investigating (model={MODEL})…", flush=True)

    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=MAX_TOKENS, system=system, tools=tools,
        messages=[{"role": "user", "content": prompt}],
    )
    async for message in runner:                     # one BetaMessage per model round-trip
        turns += 1
        for b in message.content:
            if b.type == "text" and b.text.strip():
                final.append(b.text.strip())
            elif b.type == "tool_use":
                name = b.name
                if name in read_names:
                    reads += 1
                    read_tools.add(name)
                    kind = "read"
                else:
                    writes += 1
                    kind = "write"
                if live:
                    n = reads if kind == "read" else writes
                    print(f"    [{time.time() - t0:4.0f}s] {kind} #{n}  {name}({_fmt_args(dict(b.input) if b.input else {})})",
                          flush=True)
        u = message.usage
        for k in tot:
            tot[k] += getattr(u, k, 0) or 0

    in_tok, out_tok = tot["input_tokens"], tot["output_tokens"]
    cache_r, cache_w = tot["cache_read_input_tokens"], tot["cache_creation_input_tokens"]
    return {
        "reads": reads, "writes": writes, "tools": sorted(read_tools),
        "cost": _cost(MODEL, in_tok, out_tok, cache_r, cache_w), "turns": turns,
        "wall": round(time.time() - t0, 1), "text": "\n".join(final),
        "in": in_tok, "out": out_tok, "cache_r": cache_r, "cache_w": cache_w,
        # cache-neutral input: what the input would have cost with no prompt cache at all
        "logical_in": in_tok + cache_r + cache_w,
    }
