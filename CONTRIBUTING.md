# Contributing

1. Create a branch from `main`.
2. Never commit `.env` files, API keys, or local SQLite databases.
3. Keep database writes behind validated MCP tools.
4. Add direct behavior tests and update `client_test.py` for new tools.
5. Run the quality checks in the README before opening a pull request.

UI changes should preserve readable contrast, responsive layout, USD formatting,
and the separation between manual entry, assistant chat, and insights.
