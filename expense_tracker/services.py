"""Business rules and transaction boundaries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db_setup import CATEGORIES

from .idempotency import expense_fingerprint
from .models import Category, Expense, User
from .repositories import ExpenseRepository, UserRepository
from .schemas import ExpenseCreate, ExpenseUpdate
from .security import hash_password, verify_password


class AccountService:
    def __init__(self, session: Session):
        self.session = session
        self.users = UserRepository(session)

    def register(self, email: str, password: str, display_name: str) -> User:
        if self.users.by_email(email):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
        try:
            user = self.users.add(
                User(
                    email=email,
                    display_name=display_name,
                    password_hash=hash_password(password),
                )
            )
            self.session.add_all(
                [Category(user_id=user.id, name=name) for name in CATEGORIES]
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Email is already registered"
            ) from exc
        self.session.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> User:
        user = self.users.by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user


class ExpenseService:
    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.repo = ExpenseRepository(session, user_id)

    def add_category(self, name: str) -> Category:
        if self.repo.category_by_name(name):
            raise HTTPException(status.HTTP_409_CONFLICT, "Category already exists")
        try:
            category = self.repo.add_category(name)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Category already exists"
            ) from exc
        return category

    def create_expense(
        self, payload: ExpenseCreate, idempotency_key: str | None
    ) -> tuple[Expense, bool]:
        fingerprint = expense_fingerprint(
            payload.expense_date,
            payload.amount,
            payload.category_id,
            payload.description,
        )
        if idempotency_key is not None:
            if not idempotency_key.strip() or len(idempotency_key) > 128:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Idempotency-Key must be nonblank and at most 128 characters",
                )
            existing = self.repo.expense_by_idempotency_key(idempotency_key)
            if existing:
                return self._replay(existing, fingerprint)
        if not self.repo.category(payload.category_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
        try:
            expense = self.repo.add_expense(
                expense_date=payload.expense_date,
                amount=payload.amount,
                category_id=payload.category_id,
                description=payload.description,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=fingerprint if idempotency_key else None,
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            if idempotency_key:
                existing = self.repo.expense_by_idempotency_key(idempotency_key)
                if existing:
                    return self._replay(existing, fingerprint)
            raise
        return expense, False

    @staticmethod
    def _replay(expense: Expense, fingerprint: str) -> tuple[Expense, bool]:
        if expense.idempotency_fingerprint != fingerprint:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Idempotency-Key was already used with a different request",
            )
        return expense, True

    def update_expense(self, expense_id: int, payload: ExpenseUpdate) -> Expense:
        expense = self.require_expense(expense_id)
        changes = payload.model_dump(exclude_unset=True)
        category_id = changes.get("category_id")
        if category_id is not None and not self.repo.category(category_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
        for field, value in changes.items():
            setattr(expense, field, value)
        self.session.commit()
        self.session.refresh(expense, attribute_names=["category"])
        return expense

    def delete_expense(self, expense_id: int) -> None:
        expense = self.require_expense(expense_id)
        self.repo.delete(expense)
        self.session.commit()

    def require_expense(self, expense_id: int) -> Expense:
        expense = self.repo.expense(expense_id)
        if not expense:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
        return expense

    def summary(self, month: str) -> tuple[int, Decimal, list[dict]]:
        try:
            year_text, month_text = month.split("-", 1)
            year, month_number = int(year_text), int(month_text)
            start = date(year, month_number, 1)
            if start.month == 12:
                end = date(start.year + 1, 1, 1)
            else:
                end = date(start.year, start.month + 1, 1)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Month must use YYYY-MM format"
            ) from exc
        rows = self.repo.monthly_summary(start, end)
        by_category = [
            {"category": name, "count": count, "total": total}
            for name, count, total in rows
        ]
        return (
            sum(row["count"] for row in by_category),
            sum((row["total"] for row in by_category), Decimal("0.00")),
            by_category,
        )
