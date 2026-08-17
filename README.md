# Expense Tracker Agent

An expense-tracking application with a Streamlit interface, an Anthropic Claude
agent, an MCP tool server, and a local SQLite database.

## Features

- Add expenses with a form or natural-language request
- Track dates, amounts, descriptions, and categories
- Search, update, delete, and summarize expenses through MCP tools
- View totals, recent transactions, and category spending in Streamlit
- Answer questions about expenses, personal finance, banking, and credit cards
- Keep application data in a local SQLite file

## Architecture

```text
Streamlit / CLI
      |
      v
Claude agent ---- MCP client ---- stdio ---- MCP server ---- sqlite3 ---- expenses.db
      |
      +---- direct answers for general finance, banking, and card questions
```

Claude selects tools but does not access SQLite directly. The MCP server owns
all database reads and writes.

## Project files

| File | Purpose |
|---|---|
| `db_setup.py` | Creates the schema and starter categories |
| `server.py` | Exposes database operations as MCP tools |
| `mcp_client.py` | Starts the MCP server and calls its tools over stdio |
| `client_test.py` | Runs a standalone smoke test for every MCP tool |
| `agent.py` | Implements the Claude tool-calling loop and CLI |
| `streamlit_app.py` | Provides the form, chat interface, and insights dashboard |

## Requirements

- Python 3.11 or newer
- An Anthropic API key for the assistant

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy the environment template and set `ANTHROPIC_API_KEY`:

```powershell
Copy-Item .env.example .env
```

Create the database and starter categories:

```powershell
python db_setup.py
```

## Run

Start the Streamlit application:

```powershell
streamlit run streamlit_app.py
```

Run the interactive command-line assistant:

```powershell
python agent.py
```

The MCP server uses stdio and is started automatically by the client. It does
not need to be started separately.

## Test

Run the MCP smoke test:

```powershell
python client_test.py
```

List the available tools and their arguments:

```powershell
python client_test.py list
```

Install development dependencies and verify formatting:

```powershell
python -m pip install -r requirements-dev.txt
python -m black --check .
```

## MCP tools

The server exposes 18 tools:

- Category management: `list_categories`, `add_category`, `rename_category`,
  `delete_category`, `get_category_name`
- Expense management: `add_expense`, `update_expense`, `delete_expense`,
  `list_expenses`, `search_expenses`, `expenses_by_category`,
  `total_expense_by_category`, `total_expense`, `monthly_summary`
- Supporting queries: `current_date`, `find_category`, `get_expense`,
  `expenses_between`

## Configuration

| Variable | Required | Default |
|---|---:|---|
| `ANTHROPIC_API_KEY` | Yes | — |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-5` |
| `AGENT_EFFORT` | No | `medium` |
| `EXPENSE_DB` | No | `expenses.db` beside the source files |

The `.env` file and `expenses.db` are excluded from Git. Do not commit API keys
or personal expense data.

To recreate the local database with an empty expenses table:

```powershell
python db_setup.py --reset
```
