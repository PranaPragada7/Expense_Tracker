"""Unit tests for MCP result conversion and session delegation."""

import asyncio
from types import SimpleNamespace

from mcp_client import ExpenseMCPClient, tool_schema, unwrap


def test_schema_and_result_unwrapping():
    assert tool_schema(SimpleNamespace(inputSchema={"type": "object"})) == {
        "type": "object"
    }
    assert tool_schema(SimpleNamespace(input_schema={"type": "string"})) == {
        "type": "string"
    }
    assert unwrap(SimpleNamespace(structuredContent={"result": {"ok": True}})) == {
        "ok": True
    }
    assert unwrap(
        SimpleNamespace(
            structuredContent=None,
            content=[SimpleNamespace(text='{"total": 10}')],
        )
    ) == {"total": 10}
    assert (
        unwrap(
            SimpleNamespace(
                structuredContent=None,
                content=[SimpleNamespace(text="plain text")],
            )
        )
        == "plain text"
    )


def test_client_delegates_to_session():
    calls = []

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=["one"])

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return SimpleNamespace(
                structuredContent={"result": {"ok": True}}, content=[]
            )

    client = ExpenseMCPClient()
    client.session = Session()

    async def run():
        tools = await client.list_tools()
        first = await client.call("add_expense", amount=12)
        second = await client.call_with_args("find_category", {"name": "food"})
        return tools, first, second

    tools, first, second = asyncio.run(run())
    assert tools == ["one"]
    assert first == {"ok": True}
    assert second == {"ok": True}
    assert calls == [
        ("add_expense", {"amount": 12}),
        ("find_category", {"name": "food"}),
    ]
