# ── Builder stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Install build dependencies (if any future C-extensions are needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency manifests first for optimal layer caching
COPY pyproject.toml ./
# Create a stub app package so pip install . can resolve [tool.setuptools.packages.find]
# The real app code is copied in the runtime stage.
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir .

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code (changes most frequently — last layer)
COPY app ./app

# Alembic configuration and migrations (needed for alembic upgrade head at startup)
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=3)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
