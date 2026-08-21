"""Migration-backed PostgreSQL smoke test used by CI infrastructure checks."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from expense_tracker.api import create_app
from expense_tracker.config import Settings

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
def test_postgres_registration_and_expense_round_trip():
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
