"""Serve a DataPlane view to the agent as one MCP `query` tool."""
from claude_agent_sdk import tool, create_sdk_mcp_server


def make_navflow_mcp(dp, server_name: str = "navflow"):
    @tool(
        "query",
        "Read ONE time-ordered, correlated view of everything that happened to a service in a "
        "window: metrics, logs, config, deploys, and alerts, already merged. Call this once for the "
        "affected service instead of querying each system separately.",
        {"type": "object", "properties": {
            "view": {"type": "string", "description": "view name, e.g. service_timeline"},
            "key": {"type": "string", "description": "entity to key by, e.g. api-server"},
            "window": {"type": "string", "description": "time window, e.g. 15m"}},
         "required": ["view", "key", "window"]},
    )
    async def query(args):
        payload = await dp.query(
            args.get("view", "service_timeline"),
            args.get("key", "api-server"),
            args.get("window", "15m"),
        )
        return {"content": [{"type": "text", "text": payload}]}

    return create_sdk_mcp_server(name=server_name, version="0.1.0", tools=[query])
