"""Standalone smoke test and command-line client for the MCP server.

Usage:

    python client_test.py
    python client_test.py list
    python client_test.py call total_expense
    python client_test.py call find_category '{"name":"Food"}'
"""

import asyncio
import json
import sys
from uuid import uuid4

from mcp_client import ExpenseMCPClient, tool_schema


def show(title: str, data) -> None:
    print(f"\n--- {title} " + "-" * max(3, 60 - len(title)))
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def require_ok(result: dict, action: str) -> dict:
    if not result.get("ok"):
        raise RuntimeError(f"{action} failed: {result}")
    return result


async def list_tools_cmd() -> None:
    async with ExpenseMCPClient() as client:
        tools = await client.list_tools()
        print(f"{len(tools)} tools exposed by the server:\n")
        for tool in tools:
            params = ", ".join(tool_schema(tool).get("properties", {}))
            print(f"  {tool.name}({params})")
            print(f"      {(tool.description or '').splitlines()[0]}")


async def call_cmd(name: str, args_json: str = "{}") -> None:
    async with ExpenseMCPClient() as client:
        show(name, await client.call(name, **json.loads(args_json)))


async def smoke_test() -> None:
    """Exercise all MCP tools and remove temporary records afterward."""
    suffix = uuid4().hex[:8]
    test_category = f"SmokeTest-{suffix}"
    renamed_category = f"SmokeTestRenamed-{suffix}"
    test_description = f"Smoke test expense {suffix}"
    category_id = None
    expense_id = None

    async with ExpenseMCPClient() as client:
        try:
            tools = await client.list_tools()
            if len(tools) != 18:
                raise RuntimeError(f"Expected 18 tools, found {len(tools)}.")
            print("Connected. Server exposes 18 tools.")

            show("current_date", await client.call("current_date"))
            categories = await client.call("list_categories")
            show("list_categories", categories)

            food = await client.call("find_category", name="Food")
            shopping = await client.call("find_category", name="Shopping")
            if not food.get("found") or not shopping.get("found"):
                raise RuntimeError("Smoke test requires Food and Shopping categories.")
            show("find_category('Food')", food)
            show(
                "get_category_name",
                await client.call("get_category_name", category_id=shopping["id"]),
            )

            created = require_ok(
                await client.call("add_category", name=test_category),
                "add_category",
            )
            category_id = created["id"]
            show("add_category", created)
            show(
                "rename_category",
                require_ok(
                    await client.call(
                        "rename_category",
                        category_id=category_id,
                        new_name=renamed_category,
                    ),
                    "rename_category",
                ),
            )
            show(
                "delete_category",
                require_ok(
                    await client.call("delete_category", category_id=category_id),
                    "delete_category",
                ),
            )
            category_id = None

            added = require_ok(
                await client.call(
                    "add_expense",
                    date="today",
                    description=test_description,
                    amount=25.00,
                    category_id=food["id"],
                ),
                "add_expense",
            )
            expense_id = added["id"]
            show("add_expense", added)
            show(
                "get_expense",
                await client.call("get_expense", expense_id=expense_id),
            )
            show(
                "search_expenses",
                await client.call("search_expenses", text=test_description),
            )
            show(
                "update_expense",
                require_ok(
                    await client.call(
                        "update_expense", expense_id=expense_id, amount=35.00
                    ),
                    "update_expense",
                ),
            )

            show(
                "expenses_by_category",
                await client.call("expenses_by_category", category="Shopping"),
            )
            show(
                "total_expense_by_category",
                await client.call("total_expense_by_category", category="Food"),
            )
            show("total_expense", await client.call("total_expense"))
            show("monthly_summary", await client.call("monthly_summary"))
            show(
                "monthly_summary('last month')",
                await client.call("monthly_summary", month="last month"),
            )
            show(
                "expenses_between",
                await client.call(
                    "expenses_between", start_date="30 days ago", end_date="today"
                ),
            )
            show(
                "list_expenses",
                await client.call("list_expenses", limit=5),
            )

            show(
                "delete_expense",
                require_ok(
                    await client.call("delete_expense", expense_id=expense_id),
                    "delete_expense",
                ),
            )
            expense_id = None
            print("\nSmoke test finished successfully.")
        finally:
            if expense_id is not None:
                await client.call("delete_expense", expense_id=expense_id)
            if category_id is not None:
                await client.call("delete_category", category_id=category_id)


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        asyncio.run(smoke_test())
    elif argv[0] == "list":
        asyncio.run(list_tools_cmd())
    elif argv[0] == "call" and len(argv) >= 2:
        asyncio.run(call_cmd(argv[1], argv[2] if len(argv) > 2 else "{}"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
