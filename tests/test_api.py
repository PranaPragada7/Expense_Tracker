"""End-to-end API tests against an isolated relational database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from expense_tracker.api import create_app
from expense_tracker.config import DEVELOPMENT_SECRET, Settings
from expense_tracker.database import Base, build_engine, build_session_factory
from expense_tracker.logging_config import JsonFormatter
from expense_tracker.security import (
    TOKEN_ALGORITHM,
    TOKEN_ISSUER,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

TEST_SECRET = "test-secret-that-is-long-enough-for-jwt"
PASSWORD = "Correct Horse Battery Staple"


@pytest.fixture
def client():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = Settings(
        database_url="sqlite://",
        jwt_secret=TEST_SECRET,
        app_env="test",
        log_level="WARNING",
    )
    app = create_app(settings, build_session_factory(engine))
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)
    engine.dispose()


def register(client: TestClient, email: str = "owner@example.com") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": "Test Owner",
        },
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str = "owner@example.com") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/token",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["expires_in"] == 3600
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def register_and_login(
    client: TestClient, email: str = "owner@example.com"
) -> dict[str, str]:
    register(client, email)
    return login(client, email)


def test_health_authentication_and_request_context(client):
    live = client.get("/health/live", headers={"X-Request-ID": "known-request"})
    assert live.json() == {"status": "ok", "service": "expense-tracker-api"}
    assert live.headers["X-Request-ID"] == "known-request"
    assert client.get("/health/ready").json()["status"] == "ready"

    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer invalid-token"}
        ).status_code
        == 401
    )

    created = register(client, "  OWNER@Example.COM ")
    assert created["email"] == "owner@example.com"
    assert created["display_name"] == "Test Owner"
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": PASSWORD,
                "display_name": "Duplicate",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": "not-email", "password": "short", "display_name": " "},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/auth/token",
            json={"email": "owner@example.com", "password": "wrong-password"},
        ).status_code
        == 401
    )

    headers = login(client, "OWNER@example.com")
    profile = client.get("/api/v1/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["email"] == "owner@example.com"


def test_expense_crud_filters_summary_and_idempotency(client):
    headers = register_and_login(client)
    categories = client.get("/api/v1/categories", headers=headers).json()
    assert len(categories) == 8
    food_id = next(item["id"] for item in categories if item["name"] == "Food")

    education = client.post(
        "/api/v1/categories", headers=headers, json={"name": " Education "}
    )
    assert education.status_code == 201
    assert education.json()["name"] == "Education"
    assert (
        client.post(
            "/api/v1/categories", headers=headers, json={"name": "education"}
        ).status_code
        == 409
    )

    payload = {
        "expense_date": "2026-08-15",
        "amount": "12.34",
        "category_id": food_id,
        "description": " Team lunch ",
    }
    created = client.post(
        "/api/v1/expenses",
        headers={**headers, "Idempotency-Key": "lunch-2026-08-15"},
        json=payload,
    )
    assert created.status_code == 201
    expense = created.json()
    assert expense["amount"] == "12.34"
    assert expense["description"] == "Team lunch"

    replay = client.post(
        "/api/v1/expenses",
        headers={**headers, "Idempotency-Key": "lunch-2026-08-15"},
        json=payload,
    )
    assert replay.status_code == 200
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json()["id"] == expense["id"]

    assert (
        client.post(
            "/api/v1/expenses",
            headers=headers,
            json={**payload, "category_id": 99999},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/expenses",
            headers={**headers, "Idempotency-Key": "x" * 129},
            json=payload,
        ).status_code
        == 400
    )

    page = client.get(
        "/api/v1/expenses?search_text=lunch&start_date=2026-08-01&end_date=2026-08-31",
        headers=headers,
    ).json()
    assert page["total"] == 1
    assert page["items"][0]["category"] == "Food"
    assert (
        client.get(
            f"/api/v1/expenses?category_id={education.json()['id']}", headers=headers
        ).json()["total"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/expenses?start_date=2026-09-01&end_date=2026-08-01",
            headers=headers,
        ).status_code
        == 400
    )

    updated = client.patch(
        f"/api/v1/expenses/{expense['id']}",
        headers=headers,
        json={"amount": "18.50", "category_id": education.json()["id"]},
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == "18.50"
    assert updated.json()["category"] == "Education"
    assert (
        client.patch(
            f"/api/v1/expenses/{expense['id']}", headers=headers, json={}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/expenses/{expense['id']}",
            headers=headers,
            json={"category_id": 99999},
        ).status_code
        == 404
    )

    summary = client.get("/api/v1/analytics/monthly?month=2026-08", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["total"] == "18.50"
    assert summary.json()["by_category"][0]["category"] == "Education"
    assert (
        client.get(
            "/api/v1/analytics/monthly?month=2026-13", headers=headers
        ).status_code
        == 400
    )

    assert (
        client.delete(f"/api/v1/expenses/{expense['id']}", headers=headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/expenses/{expense['id']}", headers=headers).status_code
        == 404
    )


def test_users_cannot_read_or_modify_each_others_expenses(client):
    owner_headers = register_and_login(client, "owner@example.com")
    owner_categories = client.get("/api/v1/categories", headers=owner_headers).json()
    expense = client.post(
        "/api/v1/expenses",
        headers=owner_headers,
        json={
            "expense_date": "2026-08-20",
            "amount": "99.00",
            "category_id": owner_categories[0]["id"],
            "description": "Private expense",
        },
    ).json()

    other_headers = register_and_login(client, "other@example.com")
    assert (
        client.get(
            f"/api/v1/expenses/{expense['id']}", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/expenses/{expense['id']}",
            headers=other_headers,
            json={"amount": "1.00"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/expenses/{expense['id']}", headers=other_headers
        ).status_code
        == 404
    )
    assert client.get("/api/v1/expenses", headers=other_headers).json()["total"] == 0


def test_security_configuration_and_logging_helpers():
    password_hash = hash_password(PASSWORD)
    assert verify_password(PASSWORD, password_hash)
    assert not verify_password("wrong", password_hash)
    assert not verify_password(PASSWORD, "not-an-argon-hash")

    token = create_access_token(42, TEST_SECRET, 5)
    assert decode_access_token(token, TEST_SECRET) == 42

    now = datetime.now(UTC)
    bad_subject = jwt.encode(
        {
            "sub": "not-an-id",
            "iss": TOKEN_ISSUER,
            "iat": now,
            "exp": now + timedelta(minutes=1),
        },
        TEST_SECRET,
        algorithm=TOKEN_ALGORITHM,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(bad_subject, TEST_SECRET)
    expired = jwt.encode(
        {
            "sub": "1",
            "iss": TOKEN_ISSUER,
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        TEST_SECRET,
        algorithm=TOKEN_ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired, TEST_SECRET)

    with pytest.raises(ValueError, match="configured in production"):
        Settings(app_env="production", jwt_secret=DEVELOPMENT_SECRET).validate()
    with pytest.raises(ValueError, match="at least 1"):
        Settings(access_token_minutes=0).validate()
    with pytest.raises(ValueError, match="24 characters"):
        Settings(jwt_secret="short").validate()

    formatter = JsonFormatter()
    record = __import__("logging").LogRecord(
        "test", 20, __file__, 1, "hello %s", ("world",), None
    )
    assert '"message": "hello world"' in formatter.format(record)


@pytest.mark.parametrize(
    "field", ["amount", "expense_date", "category_id", "description"]
)
def test_null_update_is_rejected_without_changing_expense(client, field):
    headers = register_and_login(client)
    category = client.get("/api/v1/categories", headers=headers).json()[0]["id"]
    created = client.post(
        "/api/v1/expenses",
        headers=headers,
        json={"amount": "12.34", "category_id": category, "description": "Lunch"},
    ).json()
    path = f"/api/v1/expenses/{created['id']}"
    before = client.get(path, headers=headers).json()
    assert client.patch(path, headers=headers, json={field: None}).status_code == 422
    assert client.get(path, headers=headers).json() == before


def test_blank_names_and_descriptions_are_rejected(client):
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "blank@example.test",
                "password": PASSWORD,
                "display_name": "  ",
            },
        ).status_code
        == 422
    )
    headers = register_and_login(client)
    assert (
        client.post(
            "/api/v1/categories", headers=headers, json={"name": " \t "}
        ).status_code
        == 422
    )
    category = client.get("/api/v1/categories", headers=headers).json()[0]["id"]
    payload = {"amount": "1.00", "category_id": category, "description": " \n "}
    assert (
        client.post("/api/v1/expenses", headers=headers, json=payload).status_code
        == 422
    )
    created = client.post(
        "/api/v1/expenses", headers=headers, json={**payload, "description": "Lunch"}
    ).json()
    assert (
        client.patch(
            f"/api/v1/expenses/{created['id']}",
            headers=headers,
            json={"description": " "},
        ).status_code
        == 422
    )


def test_idempotency_conflicts_and_original_request_survive_edits(client, monkeypatch):
    from expense_tracker.repositories import ExpenseRepository

    headers = register_and_login(client)
    category = client.get("/api/v1/categories", headers=headers).json()[0]["id"]
    payload = {
        "expense_date": "2026-08-15",
        "amount": "12.30",
        "category_id": category,
        "description": "Lunch",
    }
    keyed = {**headers, "Idempotency-Key": "retry-key"}
    created = client.post("/api/v1/expenses", headers=keyed, json=payload).json()
    assert (
        client.post(
            "/api/v1/expenses", headers=keyed, json={**payload, "amount": "99.00"}
        ).status_code
        == 409
    )

    # Simulate a concurrent request that missed the committed row on its first
    # lookup. The real INSERT/flush must hit the unique constraint and recover.
    original = ExpenseRepository.expense_by_idempotency_key
    calls = 0

    def stale_once(repo, key):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original(repo, key)

    with monkeypatch.context() as scoped:
        scoped.setattr(ExpenseRepository, "expense_by_idempotency_key", stale_once)
        replay = client.post("/api/v1/expenses", headers=keyed, json=payload)
    assert replay.status_code == 200
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json()["id"] == created["id"]
    assert client.get("/api/v1/expenses", headers=headers).json()["total"] == 1

    client.patch(
        f"/api/v1/expenses/{created['id']}", headers=headers, json={"amount": "20.00"}
    )
    replay = client.post(
        "/api/v1/expenses", headers=keyed, json={**payload, "amount": "12.3"}
    )
    assert replay.status_code == 200
    assert replay.json()["amount"] == "20.00"
    assert (
        client.post(
            "/api/v1/expenses", headers=keyed, json={**payload, "amount": "20.00"}
        ).status_code
        == 409
    )
    for key in ("", "   "):
        assert (
            client.post(
                "/api/v1/expenses",
                headers={**headers, "Idempotency-Key": key},
                json=payload,
            ).status_code
            == 400
        )


def test_duplicate_registration_and_category_flush_return_conflict(client, monkeypatch):
    from expense_tracker.repositories import ExpenseRepository, UserRepository

    headers = register_and_login(client)
    with monkeypatch.context() as scoped:
        scoped.setattr(UserRepository, "by_email", lambda *args: None)
        assert (
            client.post(
                "/api/v1/auth/register",
                json={
                    "email": "owner@example.com",
                    "password": PASSWORD,
                    "display_name": "Race",
                },
            ).status_code
            == 409
        )
    with monkeypatch.context() as scoped:
        scoped.setattr(ExpenseRepository, "category_by_name", lambda *args: None)
        assert (
            client.post(
                "/api/v1/categories", headers=headers, json={"name": "Food"}
            ).status_code
            == 409
        )
    assert client.get("/api/v1/me", headers=headers).status_code == 200


def test_monthly_summary_rejects_unrepresentable_end_date(client):
    headers = register_and_login(client)
    response = client.get(
        "/api/v1/analytics/monthly", headers=headers, params={"month": "9999-12"}
    )
    assert response.status_code == 400
    assert client.get(
        "/api/v1/analytics/monthly", headers=headers, params={"month": "9999-11"}
    ).status_code == 200
