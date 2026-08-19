"""Streamlit UI for the Expense Tracker Agent.

Run with:

    streamlit run streamlit_app.py

The app offers a quick-add form, an AI assistant backed by MCP tools, and an
analytics dashboard. All displayed amounts use US dollars.
"""

import asyncio
import os
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agent import MODEL, ExpenseAgent
from db_setup import create as create_database
from db_setup import has_schema
from mcp_client import ExpenseMCPClient

load_dotenv(override=True)

DB_PATH = os.environ.get("EXPENSE_DB", str(Path(__file__).with_name("expenses.db")))
if not has_schema(DB_PATH):
    create_database(DB_PATH)

st.set_page_config(
    page_title="Expense Tracker",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
        :root {
            --ink: #13213c;
            --muted: #63708a;
            --brand: #635bff;
            --brand-dark: #4338ca;
            --mint: #2dd4bf;
            --surface: #ffffff;
            --canvas: #f5f7fb;
            --line: #e6eaf2;
        }

        .stApp {
            background:
                radial-gradient(
                    circle at 85% 5%, rgba(99, 91, 255, 0.10), transparent 25rem
                ),
                var(--canvas);
        }

        .block-container {
            max-width: 1180px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        [data-testid="stMain"] {
            color: var(--ink);
        }

        [data-testid="stSkillsNudge"] {
            display: none !important;
        }

        [data-testid="stMain"] h1,
        [data-testid="stMain"] h2,
        [data-testid="stMain"] h3,
        [data-testid="stMain"] h4,
        [data-testid="stMain"] h5,
        [data-testid="stMain"] h6,
        [data-testid="stMain"] label,
        [data-testid="stMain"] [data-testid="stMarkdownContainer"] p {
            color: var(--ink) !important;
        }

        [data-testid="stMain"] [data-baseweb="input"],
        [data-testid="stMain"] [data-baseweb="select"] > div,
        [data-testid="stMain"] [data-testid="stTextInputRootElement"],
        [data-testid="stMain"] [data-testid="stSelectbox"]
            .react-aria-ComboBox > div {
            border-color: #cfd6e4 !important;
            background: #ffffff !important;
        }

        [data-testid="stMain"] [data-baseweb="input"] input,
        [data-testid="stMain"] [data-testid="stTextInputRootElement"] input,
        [data-testid="stMain"] [data-testid="stSelectbox"] input,
        [data-testid="stMain"] [data-testid="stDateInputField"],
        [data-testid="stMain"] [data-testid="stChatInputTextArea"] {
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
        }

        [data-testid="stMain"] input::placeholder,
        [data-testid="stMain"] textarea::placeholder {
            color: #7a869c !important;
            -webkit-text-fill-color: #7a869c !important;
            opacity: 1 !important;
        }

        [data-testid="stMain"] [data-testid="stChatInput"] {
            overflow: hidden;
            border: 1px solid #cfd6e4;
            border-radius: 0.9rem;
            background: #ffffff !important;
            box-shadow: 0 8px 24px rgba(31, 42, 68, 0.07);
        }

        [data-testid="stMain"] [data-testid="stChatInput"] > div,
        [data-testid="stMain"] [data-testid="stChatInput"] > div > div,
        [data-testid="stMain"] [data-testid="stChatInput"] > div > div > div {
            background: #ffffff !important;
        }

        [data-testid="stMain"] [data-testid="stChatInput"] button {
            color: var(--brand) !important;
        }

        [data-testid="stSidebar"] {
            background: #11182b;
            border-right: 0;
        }

        [data-testid="stSidebar"] * {
            color: #eef2ff;
        }

        .brand-mark {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2.6rem;
            height: 2.6rem;
            margin-bottom: 0.8rem;
            border-radius: 0.85rem;
            background: linear-gradient(135deg, #8178ff, #2dd4bf);
            color: white;
            font-size: 1.25rem;
            font-weight: 800;
            box-shadow: 0 10px 24px rgba(99, 91, 255, 0.28);
        }

        .side-label {
            margin: 1.5rem 0 0.35rem;
            color: #94a3b8 !important;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .hero {
            position: relative;
            overflow: hidden;
            margin-bottom: 1.5rem;
            padding: 2.2rem 2.4rem;
            border: 1px solid rgba(99, 91, 255, 0.14);
            border-radius: 1.5rem;
            background: linear-gradient(120deg, #ffffff 0%, #f7f6ff 65%, #edfffb 100%);
            box-shadow: 0 18px 48px rgba(31, 42, 68, 0.08);
        }

        .hero::after {
            content: "$";
            position: absolute;
            top: -2.7rem;
            right: 1rem;
            color: rgba(99, 91, 255, 0.07);
            font-size: 13rem;
            font-weight: 800;
            line-height: 1;
        }

        .hero h1 {
            margin: 0;
            color: var(--ink);
            font-size: clamp(2rem, 5vw, 3.35rem);
            letter-spacing: -0.045em;
        }

        [data-testid="stMetric"] {
            padding: 1.25rem 1.35rem;
            border: 1px solid var(--line);
            border-radius: 1rem;
            background: rgba(255, 255, 255, 0.92);
            box-shadow: 0 8px 24px rgba(31, 42, 68, 0.05);
        }

        div[data-testid="stHorizontalBlock"]
            > div[data-testid="stColumn"]:nth-child(1)
            [data-testid="stMetric"] {
            border-top: 4px solid #635bff;
        }

        div[data-testid="stHorizontalBlock"]
            > div[data-testid="stColumn"]:nth-child(2)
            [data-testid="stMetric"] {
            border-top: 4px solid #14b8a6;
        }

        div[data-testid="stHorizontalBlock"]
            > div[data-testid="stColumn"]:nth-child(3)
            [data-testid="stMetric"] {
            border-top: 4px solid #3b82f6;
        }

        div[data-testid="stHorizontalBlock"]
            > div[data-testid="stColumn"]:nth-child(4)
            [data-testid="stMetric"] {
            border-top: 4px solid #f59e0b;
        }

        [data-testid="stMetricLabel"] {
            color: var(--muted);
        }

        [data-testid="stMetricValue"] {
            color: var(--ink);
        }

        [data-testid="stForm"] {
            padding: 1.55rem;
            border: 1px solid var(--line);
            border-radius: 1.15rem;
            background: var(--surface);
            box-shadow: 0 10px 30px rgba(31, 42, 68, 0.06);
        }

        .section-copy {
            margin: -0.5rem 0 1.3rem;
            color: var(--muted) !important;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.4rem;
            padding: 0.35rem;
            border: 1px solid var(--line);
            border-radius: 0.9rem;
            background: linear-gradient(90deg, #eeecff, #e8faf7);
        }

        .stTabs [data-baseweb="tab"] {
            height: 2.8rem;
            padding: 0 1.25rem;
            border-radius: 0.65rem;
        }

        .stTabs [data-baseweb="tab"] p {
            color: #58657c !important;
            font-weight: 650;
        }

        .stTabs [aria-selected="true"] {
            background: white;
            box-shadow: 0 4px 12px rgba(31, 42, 68, 0.08);
        }

        .stTabs [aria-selected="true"] p {
            color: var(--brand) !important;
        }

        [data-testid="stChatMessage"] {
            border: 1px solid var(--line);
            border-radius: 1rem;
            background: rgba(255, 255, 255, 0.88);
        }

        div.stButton > button,
        div.stFormSubmitButton > button {
            border: 0;
            border-radius: 0.75rem;
            background: linear-gradient(135deg, var(--brand), var(--brand-dark));
            color: white;
            font-weight: 700;
        }

        div.stButton > button:hover,
        div.stFormSubmitButton > button:hover {
            color: white;
            box-shadow: 0 8px 18px rgba(99, 91, 255, 0.24);
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# Data and MCP helpers
# ----------------------------------------------------------------------
@st.cache_data(ttl=2)
def load_tables(db_path: str):
    """Load dashboard data directly from SQLite for fast rendering."""
    con = sqlite3.connect(db_path)
    try:
        expenses = pd.read_sql_query(
            "SELECT e.id, e.expense_date AS date, c.name AS category, "
            "e.amount, e.description "
            "FROM expenses e LEFT JOIN categories c ON c.id = e.category_id "
            "ORDER BY e.expense_date DESC, e.id DESC",
            con,
        )
        categories = pd.read_sql_query(
            "SELECT id, name FROM categories ORDER BY name", con
        )
    finally:
        con.close()
    return expenses, categories


async def _turn(message: str, history):
    async with ExpenseAgent(verbose=False) as agent:
        agent.history = history
        reply, tool_log = await agent.chat(message)
        return reply, agent.history, tool_log


async def _add_expense(
    expense_date: date, description: str, amount: float, category_id: int
):
    """Create an expense through the same MCP server used by the agent."""
    async with ExpenseMCPClient() as client:
        return await client.call(
            "add_expense",
            date=expense_date.isoformat(),
            description=description,
            amount=amount,
            category_id=category_id,
        )


def ask_agent(message: str):
    return asyncio.run(_turn(message, st.session_state.claude_history))


def create_expense(
    expense_date: date, description: str, amount: float, category_id: int
):
    return asyncio.run(_add_expense(expense_date, description, amount, category_id))


def init_state():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("claude_history", [])
    st.session_state.setdefault("notice", None)


def handle_chat(prompt: str):
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        reply, history, tool_log = ask_agent(prompt)
        st.session_state.claude_history = history
    except Exception as exc:
        reply, tool_log = f"⚠️ {type(exc).__name__}: {exc}", []
    st.session_state.messages.append(
        {"role": "assistant", "content": reply, "tools": tool_log}
    )
    load_tables.clear()


# ----------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------
init_state()
expenses, categories = load_tables(DB_PATH)

with st.sidebar:
    st.markdown('<div class="brand-mark">$</div>', unsafe_allow_html=True)
    st.header("Expense Tracker")
    st.caption("Personal finance, without the spreadsheet work.")

    st.markdown('<div class="side-label">Configuration</div>', unsafe_allow_html=True)
    st.caption(f"AI model · {MODEL}")
    st.caption("Tool layer · MCP / stdio")
    st.caption(f"Data · {Path(DB_PATH).name}")
    st.caption("Currency · USD")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY is missing. Add it to .env and restart.")

    st.markdown('<div class="side-label">Conversation</div>', unsafe_allow_html=True)
    if st.button("Clear AI conversation", width="stretch"):
        st.session_state.messages = []
        st.session_state.claude_history = []
        st.rerun()

st.markdown(
    """
    <section class="hero">
        <h1>Expense Tracker</h1>
    </section>
    """,
    unsafe_allow_html=True,
)

this_month = expenses[
    expenses["date"].str.startswith(date.today().strftime("%Y-%m"), na=False)
]
top_category = "—"
if not expenses.empty:
    top_category = expenses.groupby("category")["amount"].sum().idxmax()

metric_total, metric_month, metric_entries, metric_category = st.columns(4)
metric_total.metric("Total spent", f"${expenses['amount'].sum():,.2f}")
metric_month.metric("This month", f"${this_month['amount'].sum():,.2f}")
metric_entries.metric("Transactions", f"{len(expenses):,}")
metric_category.metric("Top category", top_category)

add_tab, chat_tab, insights_tab = st.tabs(
    ["＋ Add expense", "✦ AI assistant", "▥ Insights"]
)

with add_tab:
    st.subheader("Add a new expense")
    st.markdown(
        '<p class="section-copy">Choose a category, enter the amount, and '
        "record the date of the purchase.</p>",
        unsafe_allow_html=True,
    )

    notice = st.session_state.pop("notice", None)
    if notice:
        st.success(notice)

    if categories.empty:
        st.warning("Add at least one category before recording an expense.")
    else:
        category_names = categories["name"].tolist()
        category_ids = dict(zip(categories["name"], categories["id"], strict=True))

        with st.form("quick_add_expense", clear_on_submit=True):
            category_col, amount_col = st.columns(2)
            with category_col:
                selected_category = st.selectbox(
                    "Expense category",
                    options=category_names,
                    help="Categories are loaded from the SQLite database.",
                )
            with amount_col:
                selected_amount = st.text_input(
                    "Amount (USD)",
                    placeholder="0.00",
                    help="Enter a whole or decimal amount, such as 25 or 25.50.",
                )

            description_col, date_col = st.columns([2, 1])
            with description_col:
                selected_description = st.text_input("Expense for")
            with date_col:
                selected_date = st.date_input("Expense date", value=date.today())

            submitted = st.form_submit_button("Add Expense", width="stretch")

        if submitted:
            description = selected_description.strip()
            amount_text = selected_amount.strip().replace("$", "").replace(",", "")
            try:
                amount = Decimal(amount_text)
            except InvalidOperation:
                amount = Decimal("0")

            if amount <= 0:
                st.error("Enter an amount greater than $0.00.")
            elif not description:
                st.error("Enter what the expense was for.")
            else:
                try:
                    result = create_expense(
                        expense_date=selected_date,
                        description=description,
                        amount=float(amount),
                        category_id=int(category_ids[selected_category]),
                    )
                    if not result.get("ok"):
                        raise RuntimeError(
                            result.get("error", "The expense was not saved.")
                        )
                    load_tables.clear()
                    st.session_state.notice = (
                        f"Saved ${result['amount']:,.2f} for {result['category']} "
                        f"on {result['expense_date']}."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save the expense: {exc}")

with chat_tab:
    st.subheader("Ask about your spending")
    st.markdown(
        '<p class="section-copy">The assistant can add, search, update, '
        "summarize, and remove expenses through MCP tools.</p>",
        unsafe_allow_html=True,
    )

    if not st.session_state.messages:
        st.info(
            "Ask about expenses, personal finance, banking, credit cards, "
            "or the database."
        )

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("tools"):
                with st.expander(f"{len(message['tools'])} MCP tool call(s)"):
                    for step in message["tools"]:
                        st.markdown(f"**{step['tool']}**")
                        st.json(
                            {"arguments": step["args"], "result": step["result"]},
                            expanded=False,
                        )

    if prompt := st.chat_input("Ask about expenses, banking, cards, or finances"):
        handle_chat(prompt)
        st.rerun()

with insights_tab:
    st.subheader("Spending insights")
    st.markdown(
        '<p class="section-copy">Review every transaction and compare totals '
        "across categories.</p>",
        unsafe_allow_html=True,
    )

    table_col, chart_col = st.columns([1.7, 1])
    with table_col:
        st.markdown("#### Recent expenses")
        st.dataframe(
            expenses,
            width="stretch",
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", format="%d"),
                "date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
                "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
                "category": "Category",
                "description": "Description",
            },
        )

    with chart_col:
        st.markdown("#### Spend by category")
        if expenses.empty:
            st.info("Add an expense to see your category chart.")
        else:
            category_totals = (
                expenses.groupby("category", as_index=False)["amount"]
                .sum()
                .set_index("category")
            )
            st.bar_chart(category_totals, color="#635bff")

    if st.button("Refresh data"):
        load_tables.clear()
        st.rerun()
