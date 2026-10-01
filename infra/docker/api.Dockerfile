FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.11.15 \
    && uv sync --frozen --no-dev --no-install-project

COPY apps ./apps
COPY packages ./packages
COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
