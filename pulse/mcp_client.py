"""MCP client: starts mcp_server.py over stdio, lists its tools and calls them.

The app never calls a write tool directly. It first records a human approval
(pulse.approval.record_approval) and passes that token with the call.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .approval import RUNTIME

SERVER = Path(__file__).resolve().parent.parent / "mcp_server.py"


def _params() -> StdioServerParameters:
    env = {**os.environ, "PULSE_RUNTIME_DIR": str(RUNTIME)}
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


async def _list_tools() -> list[dict]:
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.list_tools()
            return [{"name": t.name, "description": t.description, "input_schema": t.inputSchema} for t in res.tools]


async def _call(tool: str, args: dict) -> dict:
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
            if res.structuredContent:
                out = res.structuredContent
                return out.get("result", out) if isinstance(out, dict) else {"result": out}
            text = "".join(getattr(c, "text", "") for c in res.content)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"ok": not res.isError, "text": text}


def list_tools() -> list[dict]:
    return asyncio.run(_list_tools())


def call_tool(tool: str, args: dict) -> dict:
    return asyncio.run(_call(tool, args))
