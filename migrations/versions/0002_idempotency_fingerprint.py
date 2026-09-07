"""Persist creation fingerprints; snapshot existing keyed expenses on upgrade.

Revision ID: 0002
Revises: 0001
"""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "expenses", sa.Column("idempotency_fingerprint", sa.String(64), nullable=True)
    )
    expenses = sa.table(
        "expenses",
        sa.column("id", sa.Integer),
        sa.column("expense_date", sa.Date),
        sa.column("amount", sa.Numeric(12, 2)),
        sa.column("category_id", sa.Integer),
        sa.column("description", sa.String),
        sa.column("idempotency_key", sa.String),
        sa.column("idempotency_fingerprint", sa.String),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(expenses).where(expenses.c.idempotency_key.is_not(None))
    ).mappings()
    for row in rows:
        encoded = json.dumps(
            [
                row["expense_date"].isoformat(),
                format(row["amount"], ".2f"),
                row["category_id"],
                row["description"],
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        connection.execute(
            expenses.update()
            .where(expenses.c.id == row["id"])
            .values(
                idempotency_fingerprint=hashlib.sha256(
                    encoded.encode("utf-8")
                ).hexdigest()
            )
        )


def downgrade() -> None:
    op.drop_column("expenses", "idempotency_fingerprint")
