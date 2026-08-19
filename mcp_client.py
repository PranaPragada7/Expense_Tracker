"""
mcp_client.py
=============
A small reusable MCP client wrapper used by client_test.py, agent.py and the
Streamlit app. It launches server.py over stdio and exposes list_tools()/call().

Works with both the 1.x and 2.x MCP Python SDKs (the field names changed
between them, so the helpers below read either spelling).
"""

import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

SERVER = Path(__file__).with_name("server.py")


def tool_schema(tool) -> dict:
    """JSON schema of a tool's arguments (SDK 1.x: inputSchema, 2.x: input_schema)."""
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    return schema or {}


def unwrap(result) -> Any:
    """Turn an MCP CallToolResult into plain Python data."""
    structured = getattr(result, "structuredContent", None) or getattr(
        result, "structured_content", None
    )
    if structured:
        return (
            structured.get("result", structured)
            if isinstance(structured, dict)
            else structured
        )

    chunks = [
        c.text
        for c in (getattr(result, "content", None) or [])
        if getattr(c, "text", None)
    ]
    text = "\n".join(chunks)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


class ExpenseMCPClient:
    """Async context manager around a stdio MCP session.

    async with ExpenseMCPClient() as client:
        print(await client.call("total_expense"))
    """

    def __init__(self, server_script: Path = SERVER):
        self.server_script = Path(server_script)
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def __aenter__(self) -> "ExpenseMCPClient":
        server_env = get_default_environment()
        if db_path := os.environ.get("EXPENSE_DB"):
            server_env["EXPENSE_DB"] = db_path

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_script)],
            cwd=str(self.server_script.parent),
            env=server_env,
        )
        streams = await self._stack.enter_async_context(stdio_client(params))
        read, write = streams[0], streams[1]
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()
        self.session = None

    async def list_tools(self) -> list:
        return (await self.session.list_tools()).tools

    async def call(self, tool_name: str, /, **kwargs) -> Any:
        """Call a tool by name with keyword arguments.

        `tool_name` is positional-only so that tools with a `name` argument
        (e.g. find_category) still work.
        """
        return unwrap(await self.session.call_tool(tool_name, kwargs))

    async def call_with_args(self, tool_name: str, arguments: dict) -> Any:
        """Same as call(), but takes the argument dict as produced by the LLM."""
        return unwrap(await self.session.call_tool(tool_name, arguments or {}))
