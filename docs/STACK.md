# AAA v3 stack

This document records dependencies introduced through Sprint 1.1. Versions are pinned in
`pyproject.toml` and resolved in `uv.lock`. Runtime images are pinned where the upstream
release is stable; no model image or model artifact is introduced in this sprint.

## Sprint 1.1 runtime dependencies

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| Python | 3.12 | Supported runtime | PSF-2.0 |
| FastAPI | 0.115.12 | HTTP application framework | MIT |
| Uvicorn | 0.34.2 | ASGI server | BSD-3-Clause |
| Pydantic | 2.13.5 | Typed validation and domain contracts | MIT |
| pydantic-settings | 2.9.1 | Environment-backed settings | MIT |
| SQLAlchemy | 2.0.40 | Async database engine/session foundation | MIT |
| asyncpg | 0.30.0 | PostgreSQL async driver | Apache-2.0 |
| Alembic | 1.15.2 | Database migration runner | MIT |
| redis-py | 5.2.1 | Async Redis client | MIT |
| MinIO Python SDK | 7.2.15 | S3-compatible object-storage client | Apache-2.0 |
| structlog | 25.2.0 | Structured application logging | MIT |
| HTTPX | 0.28.1 | Test client and HTTP utilities | BSD-3-Clause |

## Development tooling

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| pytest | 8.4.2 | Test runner | MIT |
| pytest-asyncio | 0.26.0 | Async test support | Apache-2.0 |
| Ruff | 0.16.9 | Linting and import checks | MIT |
| mypy | 1.20.2 | Strict static typing for `packages/` | MIT |
| import-linter | 2.15.0 | Internal package boundary checks | BSD-3-Clause |
| uv | 0.11.15 | Environment and lockfile management | Apache-2.0 |

## Local runtime images

- PostgreSQL + pgvector: `pgvector/pgvector:pg16`
- Redis: `redis:7-alpine`
- MinIO: `minio/minio:latest` (the local registry image available during Sprint 1.1; pin
  to a release digest before production use)
- API image: built locally from `infra/docker/api.Dockerfile`

The Phase 1 Compose profile starts only PostgreSQL, Redis, MinIO, and the API. Llama.cpp,
model gateway, workers, frontend flows, retrieval, and other later-phase services are not
started here. No model weights, datasets, runtime databases, or secrets belong in Git.
