"""Migration-backed PostgreSQL smoke test used by CI infrastructure checks."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local

import pytest
from fastapi.testclient import TestClient

from expense_tracker.api import create_app
from expense_tracker.config import Settings
from expense_tracker.repositories import ExpenseRepository

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
def test_postgres_registration_and_expense_round_trip(monkeypatch):
    settings = Settings(
        database_url=DATABASE_URL,
        jwt_secret="postgres-integration-secret-long-enough",
        app_env="test",
        log_level="WARNING",
    )
    email = f"ci-{uuid.uuid4()}@example.test"
    with TestClient(create_app(settings)) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "Postgres Integration Password",
                "display_name": "CI User",
            },
        )
        assert registration.status_code == 201
        token = client.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "Postgres Integration Password"},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        categories = client.get("/api/v1/categories", headers=headers).json()
        created = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-08-21",
                "amount": "25.75",
                "category_id": categories[0]["id"],
                "description": "PostgreSQL integration",
            },
        )
        assert created.status_code == 201
        assert client.get("/api/v1/expenses", headers=headers).json()["total"] == 1

        barrier = Barrier(2)
        thread_state = local()
        original = ExpenseRepository.expense_by_idempotency_key
        key = f"concurrent-{uuid.uuid4()}"

        def synchronized_lookup(repo, requested_key):
            result = original(repo, requested_key)
            if requested_key == key and not getattr(thread_state, "checked", False):
                thread_state.checked = True
                barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(
            ExpenseRepository, "expense_by_idempotency_key", synchronized_lookup
        )

        def create_concurrently():
            with TestClient(create_app(settings)) as worker:
                return worker.post(
                    "/api/v1/expenses",
                    headers={**headers, "Idempotency-Key": key},
                    json={
                        "expense_date": "2026-08-21",
                        "amount": "5.00",
                        "category_id": categories[0]["id"],
                        "description": "Concurrent retry",
                    },
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: create_concurrently(), range(2)))
        assert sorted(response.status_code for response in responses) == [200, 201]
        assert responses[0].json()["id"] == responses[1].json()["id"]
        assert client.get("/api/v1/expenses", headers=headers).json()["total"] == 2
