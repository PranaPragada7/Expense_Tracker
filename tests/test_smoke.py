"""Fast checks for database initialization and the Streamlit interface."""

import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest

from db_setup import CATEGORIES, create

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_database_starts_empty_with_starter_categories(tmp_path):
    database = tmp_path / "expenses.db"

    create(database)

    with sqlite3.connect(database) as connection:
        categories = connection.execute(
            "SELECT name FROM categories ORDER BY name"
        ).fetchall()
        expense_count = connection.execute("SELECT COUNT(*) FROM expenses").fetchone()[
            0
        ]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert [row[0] for row in categories] == sorted(CATEGORIES)
    assert expense_count == 0
    assert integrity == "ok"


def test_streamlit_app_loads_with_an_empty_database(tmp_path, monkeypatch):
    database = tmp_path / "streamlit.db"
    monkeypatch.setenv("EXPENSE_DB", str(database))

    app = AppTest.from_file(
        str(PROJECT_ROOT / "streamlit_app.py"), default_timeout=20
    ).run()

    assert not app.exception
    assert len(app.tabs) == 3
    assert sorted(app.selectbox[0].options) == sorted(CATEGORIES)
    assert [field.label for field in app.text_input] == [
        "Amount (USD)",
        "Expense for",
    ]
    assert app.date_input[0].label == "Expense date"
    assert any(button.label == "Add Expense" for button in app.button)
    assert app.chat_input[0].placeholder == (
        "Ask about expenses, banking, cards, or finances"
    )

    with sqlite3.connect(database) as connection:
        expense_count = connection.execute("SELECT COUNT(*) FROM expenses").fetchone()[
            0
        ]
    assert expense_count == 0
