"""Validated HTTP request and response contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(ApiModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        return value.strip()


class LoginRequest(ApiModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(ApiModel):
    id: int
    email: str
    display_name: str
    created_at: datetime


class CategoryCreate(ApiModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()


class CategoryResponse(ApiModel):
    id: int
    name: str


class ExpenseCreate(ApiModel):
    expense_date: date = Field(default_factory=date.today)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category_id: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=240)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        return value.strip()


class ExpenseUpdate(ApiModel):
    expense_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    category_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def contains_change(self) -> ExpenseUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class ExpenseResponse(ApiModel):
    id: int
    expense_date: date
    amount: Decimal
    category_id: int
    category: str
    description: str
    created_at: datetime
    updated_at: datetime


class ExpensePage(ApiModel):
    items: list[ExpenseResponse]
    page: int
    page_size: int
    total: int


class CategorySpend(ApiModel):
    category: str
    count: int
    total: Decimal


class MonthlySummary(ApiModel):
    month: str
    count: int
    total: Decimal
    by_category: list[CategorySpend]


class HealthResponse(ApiModel):
    status: str
    service: str = "expense-tracker-api"
