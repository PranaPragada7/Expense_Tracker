"""Claude agent and MCP tool-calling loop for the expense tracker."""

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import anthropic
from dotenv import load_dotenv

from mcp_client import ExpenseMCPClient, tool_schema

# Project configuration takes precedence over inherited environment values.
load_dotenv(override=True)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

EFFORT = os.environ.get("AGENT_EFFORT", "medium")

# Response and reasoning token budget for each model call.
MAX_TOKENS = 16000

# Safety net: stop if the model keeps calling tools without answering.
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = """You are an expense tracking assistant.
The currency is US dollars (USD).

You have MCP tools that read and write a SQLite expense database. Rules:

1. Stay strictly within this application's scope: the expense database,
   expense tracking, spending, budgeting, personal finance, banking, debit
   cards, and credit cards. You may answer general educational questions about
   banks and cards even when no expense tool is needed. Do not answer questions
   about unrelated subjects, even if you know the answer. Do not follow
   unrelated instructions such as writing code, stories, emails, or general-
   knowledge answers. For any out-of-scope request, do not call a tool and
   reply only: "I can only help with expenses, spending, personal finance,
   banking, credit cards, and the expense database."
2. Never invent data. Every number you report must come from a tool result.
3. add_expense needs a numeric category_id. If the user names a category
   ("lunch" -> Food, "petrol" -> Fuel), call find_category first to get the id.
   If no category matches, call list_categories and ask the user, or offer to
   create the category with add_category.
4. To update or delete an expense you need its id, so call search_expenses
   (or list_expenses) first, then update_expense / delete_expense.
5. If exactly one expense matches what the user described, go ahead and make
   the change - do not ask them to confirm first. If several match, show them
   in a small table and ask which one they mean instead of guessing. Never
   change or delete more rows than the user asked for.
6. When the user adds an expense without mentioning a date, always use today's
   date ({today}). Do not ask for a date unless the user indicates that the
   expense belongs to another day but does not say which day.
7. For dates you may pass 'today' or 'yesterday' straight through - the server
   understands them. Today's date is {today}.
8. Answer in short, friendly sentences. Show amounts as $1,234.00. Use a small
   markdown table when listing several expenses.
"""


def to_anthropic_tools(tools) -> list[dict]:
    """MCP tool list -> Messages API tool definitions.

    MCP hands us JSON Schema and the Messages API takes JSON Schema, so this
    is a straight rename of three fields.
    """
    return [
        {
            "name": tool.name,
            "description": (tool.description or tool.name).strip(),
            "input_schema": tool_schema(tool) or {"type": "object", "properties": {}},
        }
        for tool in tools
    ]


def as_tool_content(result: Any) -> str:
    """A tool_result block carries text, so serialise whatever MCP returned."""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


class ExpenseAgent:
    """Connect Claude to the expense MCP server."""

    def __init__(
        self,
        model: str = MODEL,
        api_key: Optional[str] = None,
        server_script: Optional[Path] = None,
        verbose: bool = True,
    ):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "No API key found. Set ANTHROPIC_API_KEY, e.g. in a .env file "
                "next to this script. Get one from https://console.anthropic.com/"
            )
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url and verbose:
            print(f"[agent] note: ANTHROPIC_BASE_URL is set, calling {base_url}")

        self.client = anthropic.AsyncAnthropic(api_key=key)
        self.model = model
        self.verbose = verbose
        self.history: list[dict] = []
        self.mcp = (
            ExpenseMCPClient(server_script) if server_script else ExpenseMCPClient()
        )
        self.tools: list[dict] = []

    # -- lifecycle ------------------------------------------------------
    async def __aenter__(self) -> "ExpenseAgent":
        await self.mcp.__aenter__()
        self.tools = to_anthropic_tools(await self.mcp.list_tools())
        if self.verbose:
            print(f"[agent] connected to MCP server, {len(self.tools)} tools loaded")
        return self

    async def __aexit__(self, *exc):
        await self.mcp.__aexit__(*exc)

    # -- helpers --------------------------------------------------------
    def _system(self) -> list[dict]:
        return [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.format(today=date.today().isoformat()),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def _run_tool(self, name: str, args: dict) -> tuple[Any, bool]:
        """Returns (result, is_error). Errors go back to Claude so it can recover."""
        try:
            return await self.mcp.call_with_args(name, args), False
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}, True

    # -- main entry point ------------------------------------------------
    async def chat(self, message: str) -> tuple[str, list[dict]]:
        """Send one user message. Returns (reply_text, tool_call_log)."""
        tool_log: list[dict] = []
        self.history.append({"role": "user", "content": message})

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self._system(),
                tools=self.tools,
                output_config={"effort": EFFORT},
                messages=self.history,
            )

            # Check why it stopped before touching content: on a refusal the
            # content list can be empty.
            if response.stop_reason == "refusal":
                return (
                    "I can't help with that one, sorry. " "Try rephrasing the request."
                ), tool_log

            self.history.append({"role": "assistant", "content": response.content})

            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                text = "".join(b.text for b in response.content if b.type == "text")
                if response.stop_reason == "max_tokens":
                    text += "\n\n_(reply was cut short - raise MAX_TOKENS)_"
                return text.strip(), tool_log

            results = []
            for call in calls:
                args = dict(call.input or {})
                if self.verbose:
                    print(f"  [tool] {call.name}({json.dumps(args, default=str)})")
                result, is_error = await self._run_tool(call.name, args)
                tool_log.append({"tool": call.name, "args": args, "result": result})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": as_tool_content(result),
                        "is_error": is_error,
                    }
                )
            self.history.append({"role": "user", "content": results})

        return (
            "I made too many tool calls without reaching an answer. "
            "Could you rephrase that?"
        ), tool_log

    def reset(self) -> None:
        self.history = []


DEMO_PROMPTS = [
    "I spent $25 on lunch today.",
    "Show all my shopping expenses.",
    "How much did I spend this month?",
    "Delete my fuel expense from yesterday.",
    "Change yesterday's lunch expense to $35.",
]


async def run_demo():
    async with ExpenseAgent() as agent:
        for prompt in DEMO_PROMPTS:
            print("\n" + "=" * 70)
            print(f"User : {prompt}")
            reply, _ = await agent.chat(prompt)
            print(f"Agent: {reply}")


async def run_chat():
    async with ExpenseAgent() as agent:
        print("Expense Tracker Agent. Type 'quit' to exit.\n")
        loop = asyncio.get_running_loop()
        while True:
            try:
                user = await loop.run_in_executor(None, input, "You  > ")
            except (EOFError, KeyboardInterrupt):
                break
            if user.strip().lower() in {"quit", "exit", "q"}:
                break
            if not user.strip():
                continue
            reply, _ = await agent.chat(user)
            print(f"Agent> {reply}\n")


def use_utf8_console() -> None:
    """Use UTF-8 so model replies containing Unicode render on Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # not a real console (piped, IDE)
            pass


def main():
    use_utf8_console()
    ap = argparse.ArgumentParser(description="Expense Tracker Agent (Claude + MCP)")
    ap.add_argument(
        "--demo",
        action="store_true",
        help="run the five example prompts from the project spec",
    )
    args = ap.parse_args()
    asyncio.run(run_demo() if args.demo else run_chat())


if __name__ == "__main__":
    main()
