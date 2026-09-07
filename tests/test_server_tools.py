"""Direct database behavior tests for the MCP tool implementations."""

from datetime import date, timedelta

import pytest

import server
from db_setup import CATEGORIES, create


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "tools.db"
    create(path)
    monkeypatch.setattr(server, "DB_PATH", str(path))
    return path


def category_id(name: str) -> int:
    return server.find_category(name)["id"]


def test_category_lifecycle_and_validation(database):
    assert [row["name"] for row in server.list_categories()] == CATEGORIES
    assert server.add_category(" ")["ok"] is False
    assert server.add_category("food")["ok"] is False

    created = server.add_category("Education")
    assert created == {"ok": True, "id": created["id"], "name": "Education"}
    assert server.get_category_name(created["id"])["name"] == "Education"

    assert server.rename_category(-1, "Courses")["ok"] is False
    assert server.rename_category(created["id"], " ")["ok"] is False
    assert server.rename_category(created["id"], "Food")["ok"] is False
    assert server.rename_category(created["id"], "Courses")["name"] == "Courses"
    assert server.delete_category(-1)["ok"] is False
    assert server.delete_category(created["id"]) == {
        "ok": True,
        "deleted": "Courses",
    }
    assert "error" in server.get_category_name(created["id"])


@pytest.mark.parametrize(
    ("today", "month_count", "month_total"),
    [(date(2026, 9, 15), 2, 52.35), (date(2026, 9, 1), 1, 12.35)],
)
def test_expense_lifecycle_and_summaries(
    database, monkeypatch, today, month_count, month_total
):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(server, "date", FixedDate)
    food = category_id("food")
    fuel = category_id("fuel")

    assert server.add_expense("today", "Lunch", 0, food)["ok"] is False
    assert server.add_expense("today", " ", 10, food)["ok"] is False
    assert server.add_expense("today", "Lunch", 10, -1)["ok"] is False

    lunch = server.add_expense("today", " Lunch ", 12.345, food)
    petrol = server.add_expense("yesterday", "Petrol", 40, fuel)
    assert lunch["amount"] == 12.35
    assert lunch["expense_date"] == today.isoformat()
    assert petrol["expense_date"] == (today - timedelta(days=1)).isoformat()

    assert len(server.list_expenses(limit=1)) == 1
    assert server.search_expenses("lunch")[0]["id"] == lunch["id"]
    assert server.get_expense(lunch["id"])["category"] == "Food"
    assert server.total_expense() == {"count": 2, "total": 52.35}

    by_category = server.expenses_by_category("foo")
    assert by_category["count"] == 1
    assert by_category["total"] == 12.35
    assert server.total_expense_by_category("Fuel")["total"] == 40.0
    assert "error" in server.expenses_by_category("unknown")
    assert "error" in server.total_expense_by_category("unknown")

    summary = server.monthly_summary("this month")
    assert summary["count"] == month_count
    assert summary["total"] == month_total

    between = server.expenses_between("today", "yesterday")
    assert between["count"] == 2
    assert between["start_date"] <= between["end_date"]

    updated = server.update_expense(
        lunch["id"],
        amount=15.5,
        expense_date="yesterday",
        description="Team lunch",
        category_id=fuel,
    )
    assert updated["after"]["amount"] == 15.5
    assert updated["after"]["category"] == "Fuel"
    assert server.update_expense(-1, amount=5)["ok"] is False
    assert server.update_expense(lunch["id"])["ok"] is False
    assert server.update_expense(lunch["id"], amount=0)["ok"] is False
    assert server.update_expense(lunch["id"], description=" ")["ok"] is False
    assert server.update_expense(lunch["id"], category_id=-1)["ok"] is False

    used = server.delete_category(fuel)
    assert used["ok"] is False
    assert "used by 2 expense" in used["error"]
    assert server.delete_expense(lunch["id"])["ok"] is True
    assert server.delete_expense(lunch["id"])["ok"] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, date.today().isoformat()),
        ("now", date.today().isoformat()),
        ("tomorrow", (date.today() + timedelta(days=1)).isoformat()),
        ("2 days ago", (date.today() - timedelta(days=2)).isoformat()),
        ("2026-07-15", "2026-07-15"),
        ("15-Jul", f"{date.today().year}-07-15"),
    ],
)
def test_date_parsing(value, expected):
    assert server._parse_date(value) == expected


def test_date_month_helpers_and_database_creation(tmp_path, monkeypatch, database):
    with pytest.raises(ValueError, match="Unsupported date"):
        server._parse_date("not-a-date")

    assert server._parse_month("July 2026") == (2026, 7)
    assert server._parse_month("07") == (date.today().year, 7)
    assert server._parse_month("last month")[1] in range(1, 13)
    assert server.current_date()["today"] == date.today().isoformat()
    assert server.find_category("")["found"] is False

    path = tmp_path / "auto.db"
    monkeypatch.setattr(server, "DB_PATH", str(path))
    server._ensure_db()
    assert path.exists()
