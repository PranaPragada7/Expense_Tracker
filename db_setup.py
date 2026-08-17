"""Create and seed the SQLite expense database."""

import argparse
import os
import sqlite3

DB_PATH = os.environ.get(
    "EXPENSE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY,
    expense_date DATE,
    amount       REAL,
    category_id  INTEGER,
    description  TEXT,
    FOREIGN KEY(category_id) REFERENCES categories(id)
);
"""

CATEGORIES = [
    "Food",
    "Travel",
    "Shopping",
    "Fuel",
    "Entertainment",
    "Medical",
    "Housing",
    "Utilities",
]


def connect(db_path=DB_PATH):
    """DB API 2.0 connection with row access by column name + FK enforcement."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def has_schema(db_path=DB_PATH) -> bool:
    """Return whether the expected tables exist in a SQLite file."""
    if not os.path.exists(db_path):
        return False
    try:
        with sqlite3.connect(db_path) as con:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
    except sqlite3.DatabaseError:
        return False
    return {row[0] for row in rows}.issuperset({"categories", "expenses"})


def create(db_path=DB_PATH, reset=False):
    con = connect(db_path)
    cur = con.cursor()

    if reset:
        cur.execute("DROP TABLE IF EXISTS expenses")
        cur.execute("DROP TABLE IF EXISTS categories")

    cur.executescript(SCHEMA)

    cur.executemany(
        "INSERT OR IGNORE INTO categories (name) VALUES (?)",
        [(name,) for name in CATEGORIES],
    )

    con.commit()

    cur.execute("SELECT COUNT(*) AS n FROM categories")
    n_cat = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM expenses")
    n_exp = cur.fetchone()["n"]
    con.close()

    print(f"Database ready: {db_path}")
    print(f"  categories : {n_cat}")
    print(f"  expenses   : {n_exp}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Create and seed the expense database.")
    ap.add_argument("--reset", action="store_true", help="drop and re-create tables")
    args = ap.parse_args()
    create(reset=args.reset)
