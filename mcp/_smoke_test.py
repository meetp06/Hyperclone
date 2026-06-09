"""Spawn mcp/server.py over stdio, list tools, and call search_memory.

Not part of the product — keeps Phase-1 verification self-contained.
Run from repo root:
    cd backend && uv run python ../mcp/_smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent


async def main() -> None:
    # Prefer agent key (Phase 3); fall back to legacy dev key.
    agent_key = os.environ.get("PIONEER_AGENT_KEY", "")
    legacy_key = (
        os.environ.get("PIONEER_MCP_API_KEY")
        or os.environ.get("MCP_API_KEY")
        or "dev-mcp-key-change-me"
    )

    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "backend"),
    }
    if agent_key:
        env["PIONEER_AGENT_KEY"] = agent_key
    else:
        env["PIONEER_MCP_API_KEY"] = legacy_key

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO / "mcp" / "server.py")],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])

            result = await session.call_tool(
                "search_memory", {"query": "which vector database?", "top_k": 3}
            )
            for i, c in enumerate(result.content):
                kind = type(c).__name__
                text = getattr(c, "text", None)
                print(f"--- content[{i}] type={kind}")
                if text is not None:
                    print(text[:600])
            if getattr(result, "structuredContent", None):
                print("--- structured ---")
                print(json.dumps(result.structuredContent, indent=2)[:800])


if __name__ == "__main__":
    asyncio.run(main())
