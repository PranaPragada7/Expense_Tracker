"""Database access scoped to an authenticated user."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .models import Category, Expense, User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user


class ExpenseRepository:
    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.user_id = user_id

    def categories(self) -> list[Category]:
        query = (
            select(Category)
            .where(Category.user_id == self.user_id)
            .order_by(Category.name)
        )
        return list(self.session.scalars(query))

    def category(self, category_id: int) -> Category | None:
        return self.session.scalar(
            select(Category).where(
                Category.id == category_id,
                Category.user_id == self.user_id,
            )
        )

    def category_by_name(self, name: str) -> Category | None:
        return self.session.scalar(
            select(Category).where(
                Category.user_id == self.user_id,
                func.lower(Category.name) == name.lower(),
            )
        )

    def add_category(self, name: str) -> Category:
        category = Category(user_id=self.user_id, name=name)
        self.session.add(category)
        self.session.flush()
        return category

    def expense(self, expense_id: int) -> Expense | None:
        return self.session.scalar(
            select(Expense)
            .options(joinedload(Expense.category))
            .where(Expense.id == expense_id, Expense.user_id == self.user_id)
        )

    def expense_by_idempotency_key(self, key: str) -> Expense | None:
        return self.session.scalar(
            select(Expense)
            .options(joinedload(Expense.category))
            .where(
                Expense.user_id == self.user_id,
                Expense.idempotency_key == key,
            )
        )

    def add_expense(
        self,
        *,
        expense_date: date,
        amount: Decimal,
        category_id: int,
        description: str,
        idempotency_key: str | None,
    ) -> Expense:
        expense = Expense(
            user_id=self.user_id,
            expense_date=expense_date,
            amount=amount,
            category_id=category_id,
            description=description,
            idempotency_key=idempotency_key,
        )
        self.session.add(expense)
        self.session.flush()
        self.session.refresh(expense, attribute_names=["category"])
        return expense

    def list_expenses(
        self,
        *,
        page: int,
        page_size: int,
        category_id: int | None,
        start_date: date | None,
        end_date: date | None,
        search_text: str | None,
    ) -> tuple[list[Expense], int]:
        filters = [Expense.user_id == self.user_id]
        if category_id is not None:
            filters.append(Expense.category_id == category_id)
        if start_date is not None:
            filters.append(Expense.expense_date >= start_date)
        if end_date is not None:
            filters.append(Expense.expense_date <= end_date)
        if search_text:
            pattern = f"%{search_text.strip()}%"
            filters.append(
                or_(
                    Expense.description.ilike(pattern),
                    Expense.category.has(Category.name.ilike(pattern)),
                )
            )

        total = self.session.scalar(select(func.count(Expense.id)).where(*filters)) or 0
        query: Select[tuple[Expense]] = (
            select(Expense)
            .options(joinedload(Expense.category))
            .where(*filters)
            .order_by(Expense.expense_date.desc(), Expense.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.scalars(query)), int(total)

    def delete(self, expense: Expense) -> None:
        self.session.delete(expense)

    def monthly_summary(self, start_date: date, end_date: date) -> list[tuple]:
        query = (
            select(
                Category.name,
                func.count(Expense.id),
                func.coalesce(func.sum(Expense.amount), 0),
            )
            .join(Expense, Expense.category_id == Category.id)
            .where(
                Expense.user_id == self.user_id,
                Expense.expense_date >= start_date,
                Expense.expense_date < end_date,
            )
            .group_by(Category.name)
            .order_by(func.sum(Expense.amount).desc())
        )
        return list(self.session.execute(query).all())
