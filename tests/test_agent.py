"""Offline tests for the Claude-to-MCP tool loop."""

import asyncio
from types import SimpleNamespace

import pytest

import agent as agent_module


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    async def create(self, **kwargs):
        return self.responses.pop(0)


class FakeMCP:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_tools(self):
        return [
            SimpleNamespace(
                name="total_expense",
                description="Return the total",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    async def call_with_args(self, name, args):
        self.calls.append((name, args))
        if self.error:
            raise self.error
        return self.result


def response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def make_agent(monkeypatch, responses):
    client = SimpleNamespace(messages=FakeMessages(responses))
    monkeypatch.setattr(agent_module.anthropic, "AsyncAnthropic", lambda **_: client)
    return agent_module.ExpenseAgent(api_key="test-key", verbose=False)


def test_tool_schema_and_content_helpers():
    tool = SimpleNamespace(
        name="sum",
        description=" Add values ",
        inputSchema={"type": "object"},
    )
    assert agent_module.to_anthropic_tools([tool]) == [
        {
            "name": "sum",
            "description": "Add values",
            "input_schema": {"type": "object"},
        }
    ]
    assert agent_module.as_tool_content("plain") == "plain"
    assert agent_module.as_tool_content({"total": 12.5}) == '{"total": 12.5}'


def test_agent_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        agent_module.ExpenseAgent()


def test_agent_runs_tool_then_returns_answer(monkeypatch):
    tool_call = SimpleNamespace(
        type="tool_use", id="tool-1", name="total_expense", input={}
    )
    text = SimpleNamespace(type="text", text="You spent $42.00.")
    expense_agent = make_agent(
        monkeypatch,
        [response(tool_call, stop_reason="tool_use"), response(text)],
    )
    expense_agent.mcp = FakeMCP(result={"count": 1, "total": 42.0})

    async def run():
        async with expense_agent as connected:
            reply, log = await connected.chat("How much did I spend?")
            return reply, log

    reply, log = asyncio.run(run())
    assert reply == "You spent $42.00."
    assert log[0]["tool"] == "total_expense"
    assert expense_agent.mcp.calls == [("total_expense", {})]
    assert len(expense_agent.tools) == 1
    expense_agent.reset()
    assert expense_agent.history == []


def test_agent_reports_tool_errors_and_truncated_answers(monkeypatch):
    tool_call = SimpleNamespace(
        type="tool_use", id="tool-1", name="total_expense", input={}
    )
    text = SimpleNamespace(type="text", text="Partial answer")
    expense_agent = make_agent(
        monkeypatch,
        [
            response(tool_call, stop_reason="tool_use"),
            response(text, stop_reason="max_tokens"),
        ],
    )
    expense_agent.mcp = FakeMCP(error=RuntimeError("database unavailable"))

    reply, log = asyncio.run(expense_agent.chat("Total?"))
    assert "reply was cut short" in reply
    assert "database unavailable" in log[0]["result"]["error"]


def test_agent_handles_model_refusal(monkeypatch):
    expense_agent = make_agent(monkeypatch, [response(stop_reason="refusal")])
    reply, log = asyncio.run(expense_agent.chat("Out of scope"))
    assert "can't help" in reply
    assert log == []
