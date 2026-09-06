"""Canonical fingerprint of an expense creation request."""

import hashlib
import json
from datetime import date
from decimal import Decimal


def expense_fingerprint(
    expense_date: date, amount: Decimal, category_id: int, description: str
) -> str:
    encoded = json.dumps(
        [expense_date.isoformat(), format(amount, ".2f"), category_id, description],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
