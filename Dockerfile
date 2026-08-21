FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system app && useradd --system --gid app app

WORKDIR /app

COPY requirements-api.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements-api.txt

COPY alembic.ini db_setup.py ./
COPY migrations ./migrations
COPY expense_tracker ./expense_tracker

USER app

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn expense_tracker.api:app --host 0.0.0.0 --port 8000"]
