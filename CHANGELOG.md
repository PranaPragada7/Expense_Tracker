# Changelog

## 2.0.0 - 2026-08-21

- Added an authenticated FastAPI service with Argon2 password hashing and
  short-lived JWT bearer tokens.
- Added user-isolated categories, expenses, filtering, pagination, monthly
  analytics, and idempotent expense creation.
- Added SQLAlchemy persistence, PostgreSQL support, and Alembic migrations.
- Added structured request logging plus liveness and database-readiness checks.
- Added a non-root API container and local Docker Compose PostgreSQL stack.
- Added SQLite API tests, cross-user authorization tests, and a migration-backed
  PostgreSQL CI job while retaining the existing MCP and Streamlit test suite.

Notable changes to Expense Tracker are documented here.

## 1.0.0 - 2026-08-19

- Added a responsive Streamlit interface for manual entry, assistant chat, and insights.
- Added 18 MCP tools for category and expense database workflows.
- Added a Claude tool-use loop with date defaults and finance-only scope controls.
- Standardized all amounts as USD and kept local databases outside version control.
- Added direct tool tests, interface checks, MCP end-to-end validation, and CI.
