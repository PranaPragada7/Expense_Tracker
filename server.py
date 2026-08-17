"""
server.py
=========
MCP server for the Expense Tracker Agent.

All tools talk to SQLite through the DB API 2.0 (sqlite3 module).
Transport is stdio, so any MCP client can launch it with:

    python server.py

Tool inventory
--------------
Category tools (5)      : list_categories, add_category, rename_category,
                          delete_category, get_category_name
Expense tools (9)       : add_expense, update_expense, delete_expense,
                          list_expenses, search_expenses, expenses_by_category,
                          total_expense_by_category, total_expense,
                          monthly_summary
Helper tools (4, added) : current_date, find_category, get_expense,
                          expenses_between
"""

import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Optional

try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer
except ImportError:  # mcp SDK 2.x renamed FastMCP -> MCPServer
    from mcp.server import MCPServer

DB_PATH = os.environ.get(
    "EXPENSE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db"),
)

mcp = MCPServer("expense-tracker")


# ----------------------------------------------------------------------
# DB API 2.0 helpers
# ----------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


# NB: `with sqlite3.connect(...)` commits or rolls back, but it does NOT close
# the connection - so these two read helpers must close it themselves, the same
# way _exec does below.
def _rows(sql: str, params: tuple = ()) -> list[dict]:
    con = _conn()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def _one(sql: str, params: tuple = ()) -> Optional[dict]:
    con = _conn()
    try:
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _exec(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    con = _conn()
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur
    finally:
        con.close()


EXPENSE_SELECT = """
SELECT e.id, e.expense_date, e.amount, e.description,
       e.category_id, c.name AS category
FROM expenses e
LEFT JOIN categories c ON c.id = e.category_id
"""


# ----------------------------------------------------------------------
# Parsing helpers (make the agent's life easy)
# ----------------------------------------------------------------------
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d-%b",
    "%d %b",
    "%b %d",
    "%B %d",
]


def _parse_date(value: Optional[str]) -> str:
    """Accepts 'today', 'yesterday', '2026-07-15', '15-07-2026', '15-Jul', ...

    Returns an ISO date string (YYYY-MM-DD). Defaults to today.
    """
    if value is None or str(value).strip() == "":
        return date.today().isoformat()

    text = str(value).strip().lower()
    today = date.today()
    if text in ("today", "now"):
        return today.isoformat()
    if text == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if text == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if text.endswith("days ago"):
        try:
            return (today - timedelta(days=int(text.split()[0]))).isoformat()
        except ValueError:
            pass

    raw = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            if "%Y" not in fmt:  # no year given -> assume current year
                parsed = parsed.replace(year=today.year)
            return parsed.isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date: {value!r}")


_MONTH_NAMES = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
_MONTH_NAMES.update({k[:3]: v for k, v in list(_MONTH_NAMES.items())})


def _parse_month(value: Optional[str]) -> tuple[int, int]:
    """Accepts '2026-07', 'July', 'July 2026', '07', 'last month', None."""
    today = date.today()
    if value is None or str(value).strip() == "":
        return today.year, today.month

    text = str(value).strip().lower()
    if text in ("this month", "current month"):
        return today.year, today.month
    if text == "last month":
        first = today.replace(day=1)
        prev = first - timedelta(days=1)
        return prev.year, prev.month

    for fmt in ("%Y-%m", "%m-%Y", "%Y/%m", "%B %Y", "%b %Y", "%B", "%b", "%m"):
        try:
            parsed = datetime.strptime(str(value).strip(), fmt)
            year = parsed.year if "%Y" in fmt else today.year
            return year, parsed.month
        except ValueError:
            continue

    words = text.replace(",", " ").split()
    month = next((_MONTH_NAMES[w] for w in words if w in _MONTH_NAMES), today.month)
    year = next((int(w) for w in words if w.isdigit() and len(w) == 4), today.year)
    return year, month


def _resolve_category(name: str) -> Optional[dict]:
    """Case-insensitive exact match first, then a LIKE match."""
    if not name:
        return None
    row = _one("SELECT * FROM categories WHERE LOWER(name) = LOWER(?)", (name.strip(),))
    if row:
        return row
    return _one(
        "SELECT * FROM categories WHERE name LIKE ? ORDER BY LENGTH(name) LIMIT 1",
        (f"%{name.strip()}%",),
    )


def _money(x: float) -> float:
    return round(float(x or 0), 2)


# ======================================================================
# Category tools (5)
# ======================================================================
@mcp.tool()
def list_categories() -> list[dict]:
    """List every expense category with its id and name."""
    return _rows("SELECT id, name FROM categories ORDER BY id")


@mcp.tool()
def add_category(name: str) -> dict:
    """Create a new expense category. Fails if the name already exists."""
    name = name.strip()
    if not name:
        return {"ok": False, "error": "Category name cannot be empty."}
    if _one("SELECT * FROM categories WHERE LOWER(name) = LOWER(?)", (name,)):
        return {"ok": False, "error": f"Category '{name}' already exists."}
    cur = _exec("INSERT INTO categories (name) VALUES (?)", (name,))
    return {"ok": True, "id": cur.lastrowid, "name": name}


@mcp.tool()
def rename_category(category_id: int, new_name: str) -> dict:
    """Rename the category with the given id."""
    new_name = new_name.strip()
    if not new_name:
        return {"ok": False, "error": "Category name cannot be empty."}
    if not _one("SELECT * FROM categories WHERE id = ?", (category_id,)):
        return {"ok": False, "error": f"No category with id {category_id}."}
    duplicate = _one(
        "SELECT id FROM categories WHERE LOWER(name) = LOWER(?) AND id != ?",
        (new_name, category_id),
    )
    if duplicate:
        return {"ok": False, "error": f"Category '{new_name}' already exists."}
    cur = _exec("UPDATE categories SET name = ? WHERE id = ?", (new_name, category_id))
    return {"ok": cur.rowcount > 0, "id": category_id, "name": new_name}


@mcp.tool()
def delete_category(category_id: int) -> dict:
    """Delete a category. Refuses if expenses are still linked to it."""
    row = _one("SELECT * FROM categories WHERE id = ?", (category_id,))
    if not row:
        return {"ok": False, "error": f"No category with id {category_id}."}
    used = _one(
        "SELECT COUNT(*) AS n FROM expenses WHERE category_id = ?", (category_id,)
    )["n"]
    if used:
        return {
            "ok": False,
            "error": f"Category '{row['name']}' is used by {used} expense(s). "
            "Delete or re-assign those expenses first.",
        }
    _exec("DELETE FROM categories WHERE id = ?", (category_id,))
    return {"ok": True, "deleted": row["name"]}


@mcp.tool()
def get_category_name(category_id: int) -> dict:
    """Get the name of a category from its id."""
    row = _one("SELECT id, name FROM categories WHERE id = ?", (category_id,))
    return row or {"error": f"No category with id {category_id}."}


# ======================================================================
# Expense tools (9)
# ======================================================================
@mcp.tool()
def add_expense(
    date: str,
    description: str,
    amount: float,
    category_id: int,
) -> dict:
    """Record a new expense.

    date        : 'today', 'yesterday', or a date like 2026-07-15 / 15-Jul.
    description : short free text, e.g. 'Lunch'.
    amount      : amount in US dollars.
    category_id : id from list_categories / find_category.
    """
    clean_description = (description or "").strip()
    clean_amount = _money(amount)
    if clean_amount <= 0:
        return {"ok": False, "error": "Amount must be greater than zero."}
    if not clean_description:
        return {"ok": False, "error": "Description cannot be empty."}

    cat = _one("SELECT * FROM categories WHERE id = ?", (category_id,))
    if not cat:
        return {
            "ok": False,
            "error": f"No category with id {category_id}. "
            "Call list_categories first.",
        }
    iso = _parse_date(date)
    cur = _exec(
        "INSERT INTO expenses (expense_date, amount, category_id, description) "
        "VALUES (?, ?, ?, ?)",
        (iso, clean_amount, category_id, clean_description),
    )
    return {
        "ok": True,
        "id": cur.lastrowid,
        "expense_date": iso,
        "amount": clean_amount,
        "category": cat["name"],
        "description": clean_description,
    }


@mcp.tool()
def update_expense(
    expense_id: int,
    amount: Optional[float] = None,
    expense_date: Optional[str] = None,
    description: Optional[str] = None,
    category_id: Optional[int] = None,
) -> dict:
    """Update an existing expense. Only the fields you pass are changed.

    Typically used after search_expenses has found the row id.
    """
    row = _one(EXPENSE_SELECT + " WHERE e.id = ?", (expense_id,))
    if not row:
        return {"ok": False, "error": f"No expense with id {expense_id}."}

    sets, params = [], []
    if amount is not None:
        if _money(amount) <= 0:
            return {"ok": False, "error": "Amount must be greater than zero."}
        sets.append("amount = ?")
        params.append(_money(amount))
    if expense_date is not None:
        sets.append("expense_date = ?")
        params.append(_parse_date(expense_date))
    if description is not None:
        if not description.strip():
            return {"ok": False, "error": "Description cannot be empty."}
        sets.append("description = ?")
        params.append(description.strip())
    if category_id is not None:
        if not _one("SELECT 1 FROM categories WHERE id = ?", (category_id,)):
            return {"ok": False, "error": f"No category with id {category_id}."}
        sets.append("category_id = ?")
        params.append(category_id)

    if not sets:
        return {"ok": False, "error": "Nothing to update."}

    params.append(expense_id)
    _exec(f"UPDATE expenses SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return {
        "ok": True,
        "before": row,
        "after": _one(EXPENSE_SELECT + " WHERE e.id = ?", (expense_id,)),
    }


@mcp.tool()
def delete_expense(expense_id: int) -> dict:
    """Delete one expense by id (find it with search_expenses first)."""
    row = _one(EXPENSE_SELECT + " WHERE e.id = ?", (expense_id,))
    if not row:
        return {"ok": False, "error": f"No expense with id {expense_id}."}
    _exec("DELETE FROM expenses WHERE id = ?", (expense_id,))
    return {"ok": True, "deleted": row}


@mcp.tool()
def list_expenses(limit: int = 50) -> list[dict]:
    """List expenses, newest first (default 50 rows)."""
    return _rows(
        EXPENSE_SELECT + " ORDER BY e.expense_date DESC, e.id DESC LIMIT ?",
        (max(1, int(limit)),),
    )


@mcp.tool()
def search_expenses(text: str) -> list[dict]:
    """Search expenses whose description or category name contains `text`.

    Use this before update_expense or delete_expense to find the row id.
    """
    pattern = f"%{(text or '').strip()}%"
    return _rows(
        EXPENSE_SELECT + " WHERE e.description LIKE ? OR c.name LIKE ?"
        " ORDER BY e.expense_date DESC, e.id DESC",
        (pattern, pattern),
    )


@mcp.tool()
def expenses_by_category(category: str) -> dict:
    """List all expenses in a category, given the category NAME (e.g. 'Shopping')."""
    cat = _resolve_category(category)
    if not cat:
        return {
            "error": f"No category matching '{category}'.",
            "available": [c["name"] for c in list_categories()],
        }
    rows = _rows(
        EXPENSE_SELECT + " WHERE e.category_id = ?"
        " ORDER BY e.expense_date DESC, e.id DESC",
        (cat["id"],),
    )
    return {
        "category": cat["name"],
        "count": len(rows),
        "total": _money(sum(r["amount"] for r in rows)),
        "expenses": rows,
    }


@mcp.tool()
def total_expense_by_category(category: str) -> dict:
    """Total amount spent in one category, given the category NAME."""
    cat = _resolve_category(category)
    if not cat:
        return {
            "error": f"No category matching '{category}'.",
            "available": [c["name"] for c in list_categories()],
        }
    row = _one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total "
        "FROM expenses WHERE category_id = ?",
        (cat["id"],),
    )
    return {"category": cat["name"], "count": row["n"], "total": _money(row["total"])}


@mcp.tool()
def total_expense() -> dict:
    """Total amount spent across all categories and all dates."""
    row = _one("SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM expenses")
    return {"count": row["n"], "total": _money(row["total"])}


@mcp.tool()
def monthly_summary(month: Optional[str] = None) -> dict:
    """Spending summary for a month, broken down by category.

    month: 'YYYY-MM', a month name, 'last month', or omit it for this month.
    """
    year, mon = _parse_month(month)
    prefix = f"{year:04d}-{mon:02d}"
    by_cat = _rows(
        "SELECT c.name AS category, COUNT(*) AS count, SUM(e.amount) AS total "
        "FROM expenses e LEFT JOIN categories c ON c.id = e.category_id "
        "WHERE strftime('%Y-%m', e.expense_date) = ? "
        "GROUP BY c.name ORDER BY total DESC",
        (prefix,),
    )
    total = _money(sum(r["total"] or 0 for r in by_cat))
    return {
        "month": prefix,
        "total": total,
        "count": sum(r["count"] for r in by_cat),
        "by_category": [
            {
                "category": r["category"],
                "count": r["count"],
                "total": _money(r["total"]),
            }
            for r in by_cat
        ],
    }


# ======================================================================
# Supporting tools (4)
# ======================================================================
@mcp.tool()
def current_date() -> dict:
    """Today's date. Call this before interpreting 'today', 'yesterday', etc."""
    today = date.today()
    return {
        "today": today.isoformat(),
        "weekday": today.strftime("%A"),
        "month": today.strftime("%Y-%m"),
    }


@mcp.tool()
def find_category(name: str) -> dict:
    """Find a category id from a name or partial name, e.g. 'food', 'shop'.

    Use this before add_expense so you can pass the correct category_id.
    """
    cat = _resolve_category(name)
    if cat:
        return {"found": True, "id": cat["id"], "name": cat["name"]}
    return {
        "found": False,
        "query": name,
        "available": [c["name"] for c in list_categories()],
    }


@mcp.tool()
def get_expense(expense_id: int) -> dict:
    """Fetch a single expense by id."""
    row = _one(EXPENSE_SELECT + " WHERE e.id = ?", (expense_id,))
    return row or {"error": f"No expense with id {expense_id}."}


@mcp.tool()
def expenses_between(start_date: str, end_date: str) -> dict:
    """All expenses between two dates (inclusive), with the total."""
    start, end = _parse_date(start_date), _parse_date(end_date)
    if start > end:
        start, end = end, start
    rows = _rows(
        EXPENSE_SELECT + " WHERE e.expense_date BETWEEN ? AND ?"
        " ORDER BY e.expense_date DESC, e.id DESC",
        (start, end),
    )
    return {
        "start_date": start,
        "end_date": end,
        "count": len(rows),
        "total": _money(sum(r["amount"] for r in rows)),
        "expenses": rows,
    }


def _ensure_db() -> None:
    """Create the database when the expected schema is missing."""
    from db_setup import create, has_schema

    if not has_schema(DB_PATH):
        create(DB_PATH)


if __name__ == "__main__":
    _ensure_db()
    mcp.run(transport="stdio")
