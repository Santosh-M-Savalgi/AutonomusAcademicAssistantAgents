# AAA v3 stack

This document records dependencies introduced through Sprint 1.3. Versions are pinned in
`pyproject.toml` and resolved in `uv.lock`. Runtime images are pinned where the upstream
release is stable; no model image or model artifact is introduced in these sprints.

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

## Sprint 1.2 authentication dependencies

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| argon2-cffi | 25.1.0 | Argon2id password hashing and verification | MIT |
| PyJWT | 2.10.1 | JWT signing and strict claim validation | MIT |

The JWT signing secret is required from `JWT_SECRET_KEY` before tokens can be issued
or validated. No default signing secret is supplied. This sprint adds no user tables,
login route, registration route, or refresh-token workflow.

## Development tooling

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| pytest | 8.4.2 | Test runner | MIT |
| pytest-asyncio | 0.26.0 | Async test support | Apache-2.0 |
| Ruff | 0.16.9 | Linting and import checks | MIT |
| mypy | 1.20.2 | Strict static typing for `packages/` | MIT |
| import-linter | 2.15.0 | Internal package boundary checks | BSD-3-Clause |
| uv | 0.11.15 | Environment and lockfile management | Apache-2.0 |

## Observability foundation

The API uses the existing `structlog` dependency (25.2.0); Sprint 1.3 adds no
observability package. Application and standard-library records are rendered as
JSON with UTC timestamps, log levels, logger names, and request context. The
request middleware creates or safely accepts an `X-Request-ID`, binds it to
structlog context variables, and returns it on successful, rejected, readiness,
and generic server-error responses.

The logging processor redacts credentials, passwords and password hashes, JWT or
Bearer token fields, database DSNs, request/response bodies, and student-answer
fields. Request bodies are not read by the middleware. Health probes report
PostgreSQL, Redis, and MinIO independently through `/readyz`; expected
dependency outages are logged as warnings without exception details, while
unexpected application failures are classified as server errors and return a
generic public response.

OpenTelemetry, Prometheus, distributed tracing, and dashboard infrastructure
remain later-phase work from the build specification. This sprint keeps the
Phase 1 logging and readiness foundation small and dependency-free.

## Test and CI infrastructure

`make test` runs unit tests and the migration wiring test without Docker. Live
dependency checks are marked `live_integration`; `make integration` starts a
fixture-owned disposable Compose stack and runs them:

```bash
make integration
```

The live command requires Docker and uses `infra/compose/test.yml` with a unique
Compose project, random loopback ports, test-only credentials, a per-test
database, and tmpfs-backed service data. It applies Alembic migrations, runs
readiness and client probes, rolls back database writes, removes Redis keys and
MinIO objects, and tears down only those ephemeral resources. CI installs from
the committed lockfile and runs Ruff, strict Mypy for `packages/`, all
import-linter contracts, unit tests, migration tests, and live service
integration tests on Linux for Python 3.12 and 3.13.

The reusable fixtures in `tests/conftest.py` build the production FastAPI app,
HTTP clients, async database sessions, Redis and MinIO owners, JWT identities,
Bearer headers, and authentication dependency overrides. Live service fixtures
are kept in `tests/integration/conftest.py`; the ordinary suite reports an
explicit skip, while `make integration` enables the live fixtures so unit tests
never access external services.

## Audited v2 infrastructure

The selective audit is recorded in
`docs/decisions/0017-phase-1-infrastructure-audit.md`. The v2 ref contains
useful reference implementations, but v3 retains its own typed boundaries and
does not restore v2 routes, orchestration, ChromaDB, cloud providers, metrics,
or OpenTelemetry dependencies.

## Local runtime images

- PostgreSQL + pgvector: `pgvector/pgvector:pg16`
- Redis: `redis:7-alpine`
- MinIO Community Edition (third-party build):
  `ghcr.io/golithus/minio:RELEASE.2025-10-15T17-29-55Z@sha256:8793e960474071520bdb91bb9a6d1793eb229fdbc9dcb7ec75ad836b69bbab40`
  Source: `https://github.com/golithus/minio-builds`; license: AGPL-3.0.
- MinIO HTTP readiness probe: `curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6`
  (dedicated Compose-sidecar probe; it is not part of the MinIO image or API runtime).
- API image: built locally from `infra/docker/api.Dockerfile`

The Phase 1 Compose profile starts only PostgreSQL, Redis, MinIO, and the API. Llama.cpp,
model gateway, workers, frontend flows, retrieval, and other later-phase services are not
started here. No model weights, datasets, runtime databases, or secrets belong in Git.
