"""Authenticated FastAPI application for Expense Tracker."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

import jwt
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import __version__
from .config import Settings
from .database import build_engine, build_session_factory, get_session
from .logging_config import configure_logging
from .models import User
from .repositories import ExpenseRepository, UserRepository
from .schemas import (
    CategoryCreate,
    CategoryResponse,
    ExpenseCreate,
    ExpensePage,
    ExpenseResponse,
    ExpenseUpdate,
    HealthResponse,
    LoginRequest,
    MonthlySummary,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from .security import create_access_token, decode_access_token
from .services import AccountService, ExpenseService

logger = logging.getLogger("expense_tracker.api")
bearer = HTTPBearer(auto_error=False)

SessionDependency = Annotated[Session, Depends(get_session)]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: SessionDependency,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Valid bearer token required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        user_id = decode_access_token(credentials.credentials, settings.jwt_secret)
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
    user = UserRepository(session).by_id(user_id)
    if not user:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(current_user)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def expense_response(expense) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense.id,
        expense_date=expense.expense_date,
        amount=expense.amount,
        category_id=expense.category_id,
        category=expense.category.name,
        description=expense.description,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def create_app(
    settings: Settings | None = None,
    session_factory=None,
) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    runtime_settings.validate()
    configure_logging(runtime_settings.log_level)
    engine = None
    if session_factory is None:
        engine = build_engine(runtime_settings.database_url)
        session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info("API started in %s mode", runtime_settings.app_env)
        yield
        if engine is not None:
            engine.dispose()

    application = FastAPI(
        title="Expense Tracker API",
        description=(
            "Authenticated, user-isolated expense management and spending analytics."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.session_factory = session_factory

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled request failure request_id=%s", request_id)
            raise
        response.headers["X-Request-ID"] = request_id
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @application.get("/health/live", response_model=HealthResponse, tags=["health"])
    def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get("/health/ready", response_model=HealthResponse, tags=["health"])
    def ready(session: SessionDependency) -> HealthResponse:
        try:
            session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Database is unavailable"
            ) from exc
        return HealthResponse(status="ready")

    @application.post(
        "/api/v1/auth/register",
        response_model=UserResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["authentication"],
    )
    def register(payload: RegisterRequest, session: SessionDependency) -> User:
        return AccountService(session).register(
            payload.email, payload.password, payload.display_name
        )

    @application.post(
        "/api/v1/auth/token",
        response_model=TokenResponse,
        tags=["authentication"],
    )
    def login(
        payload: LoginRequest,
        session: SessionDependency,
        settings: SettingsDependency,
    ) -> TokenResponse:
        user = AccountService(session).authenticate(payload.email, payload.password)
        return TokenResponse(
            access_token=create_access_token(
                user.id, settings.jwt_secret, settings.access_token_minutes
            ),
            expires_in=settings.access_token_minutes * 60,
        )

    @application.get("/api/v1/me", response_model=UserResponse, tags=["authentication"])
    def me(user: CurrentUser) -> User:
        return user

    @application.get(
        "/api/v1/categories",
        response_model=list[CategoryResponse],
        tags=["categories"],
    )
    def categories(
        user: CurrentUser,
        session: SessionDependency,
    ):
        return ExpenseRepository(session, user.id).categories()

    @application.post(
        "/api/v1/categories",
        response_model=CategoryResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["categories"],
    )
    def add_category(
        payload: CategoryCreate,
        user: CurrentUser,
        session: SessionDependency,
    ):
        return ExpenseService(session, user.id).add_category(payload.name)

    @application.post(
        "/api/v1/expenses",
        response_model=ExpenseResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["expenses"],
    )
    def add_expense(
        payload: ExpenseCreate,
        response: Response,
        user: CurrentUser,
        session: SessionDependency,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ExpenseResponse:
        expense, replayed = ExpenseService(session, user.id).create_expense(
            payload, idempotency_key
        )
        if replayed:
            response.status_code = status.HTTP_200_OK
            response.headers["X-Idempotent-Replay"] = "true"
        return expense_response(expense)

    @application.get("/api/v1/expenses", response_model=ExpensePage, tags=["expenses"])
    def list_expenses(
        user: CurrentUser,
        session: SessionDependency,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=100),
        category_id: int | None = Query(default=None, ge=1),
        start_date: date | None = None,
        end_date: date | None = None,
        search_text: str | None = Query(default=None, max_length=100),
    ) -> ExpensePage:
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "start_date cannot be after end_date"
            )
        items, total = ExpenseRepository(session, user.id).list_expenses(
            page=page,
            page_size=page_size,
            category_id=category_id,
            start_date=start_date,
            end_date=end_date,
            search_text=search_text,
        )
        return ExpensePage(
            items=[expense_response(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    @application.get(
        "/api/v1/expenses/{expense_id}",
        response_model=ExpenseResponse,
        tags=["expenses"],
    )
    def get_expense(
        expense_id: int,
        user: CurrentUser,
        session: SessionDependency,
    ) -> ExpenseResponse:
        return expense_response(
            ExpenseService(session, user.id).require_expense(expense_id)
        )

    @application.patch(
        "/api/v1/expenses/{expense_id}",
        response_model=ExpenseResponse,
        tags=["expenses"],
    )
    def update_expense(
        expense_id: int,
        payload: ExpenseUpdate,
        user: CurrentUser,
        session: SessionDependency,
    ) -> ExpenseResponse:
        return expense_response(
            ExpenseService(session, user.id).update_expense(expense_id, payload)
        )

    @application.delete(
        "/api/v1/expenses/{expense_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["expenses"],
    )
    def delete_expense(
        expense_id: int,
        user: CurrentUser,
        session: SessionDependency,
    ) -> Response:
        ExpenseService(session, user.id).delete_expense(expense_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get(
        "/api/v1/analytics/monthly",
        response_model=MonthlySummary,
        tags=["analytics"],
    )
    def monthly_summary(
        user: CurrentUser,
        session: SessionDependency,
        month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    ) -> MonthlySummary:
        count, total, by_category = ExpenseService(session, user.id).summary(month)
        return MonthlySummary(
            month=month,
            count=count,
            total=total,
            by_category=by_category,
        )

    return application


app = create_app()
