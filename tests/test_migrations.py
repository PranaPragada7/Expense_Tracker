"""Upgrade populated databases and verify fingerprint backfill and schema drift."""

from datetime import date
from decimal import Decimal

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from expense_tracker.idempotency import expense_fingerprint


def test_fingerprint_migration_preserves_existing_expenses(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users VALUES "
                "(1, 'test@example.test', 'Test', 'hash', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO categories VALUES (1, 1, 'Food')"))
        connection.execute(
            text(
                "INSERT INTO expenses (id, user_id, category_id, expense_date, amount, "
                "description, idempotency_key, created_at, updated_at) VALUES "
                "(1, 1, 1, '2026-08-15', 12.30, 'Lunch', 'old-key', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        fingerprint = connection.scalar(
            text("SELECT idempotency_fingerprint FROM expenses WHERE id = 1")
        )
        assert fingerprint == expense_fingerprint(
            date(2026, 8, 15), Decimal("12.3"), 1, "Lunch"
        )
    command.downgrade(config, "0001")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM expenses")) == 1
    engine.dispose()
