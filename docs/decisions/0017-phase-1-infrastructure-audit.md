# ADR 0017: Selective audit of AAA v2 infrastructure

## Status

Accepted for Sprint 1.3.

## Scope and source

The previous implementation was audited from the repository's
`origin/aaa-v2` ref. No Windows checkout or external source tree was accessed.
The audit was limited to infrastructure relevant to Phase 1; v2 product routes,
learning orchestration, and model workflows were not candidates for migration.

## Decisions

| Component | v2 finding | v3 decision | Reason |
|---|---|---|---|
| JWT utilities | Signed access/refresh helpers lacked required issuer, audience, reserved-claim protection, and strict token schema | **Adapted in Sprint 1.2** as `apps/api/auth/jwt.py` | Preserve the useful primitive while enforcing the v3 authentication ADR and safe configuration |
| Password hashing | v2 used bcrypt and a page-oriented password policy | **Rejected/adapted in Sprint 1.2** to Argon2id | Argon2id is the v3-approved choice; product registration and login remain out of scope |
| Auth dependencies and fixtures | v2 dependencies queried v2 user tables and its tests patched page routes | **Rejected for direct reuse**; v3 keeps opaque identity validation and dependency overrides | Avoid coupling the foundation to v2 schemas or business endpoints |
| Alembic environment | v2 used an async engine, application settings, shared metadata, and `NullPool` | **Adapted in existing v3 `alembic/env.py`** | The pattern matches v3 async SQLAlchemy and avoids importing v2 models |
| Redis client | v2 exposed a process-global singleton and returned raw exception text from probes | **Rejected/adapted** to an owned `RedisClient` | Runtime ownership is explicit and readiness responses expose only exception class names |
| MinIO/object storage | v2's Phase 1 helper checked an HTTP health URL only; later code had broader storage coupling | **Adapted** to the v3-owned MinIO SDK client | The SDK probe verifies authenticated connectivity without creating data |
| Logging and request context | v2 had separate request-context and request-logging middleware, accepted arbitrary IDs, and had no field redaction | **Adapted** into one v3 `RequestIDMiddleware` plus safe structlog processors | Avoid duplicate registration, prevent header injection, propagate context, and protect credentials/content |
| OpenTelemetry and Prometheus | v2 added optional tracing and broad metrics dependencies | **Rejected for this sprint** | The build specification places those systems in Phase 10; Phase 1 needs structured logs and dependency readiness only |
| v2 business services/routes | Included adaptive workflows, retrieval, jobs, model providers, and frontend APIs | **Rejected wholesale** | They cross Phase 1 boundaries and belong to later delivery phases |
| Test infrastructure | v2 fixtures were coupled to v2 routes, models, and external provider behavior | **Adapted selectively** into v3 app, client, resource-owner, auth, and live-service fixtures | Preserve deterministic unit tests and add explicit isolated service integration capability |

## Consequences

- The v3 codebase has no v2 route or orchestration migration.
- v2's extra dependencies, including bcrypt, ChromaDB, Prometheus, OpenTelemetry,
  cloud LLM SDKs, and resilience packages, were not added as part of this audit.
- Authentication, Alembic, MinIO, Redis, and observability behavior remains
  tested against v3 interfaces and settings rather than v2 module paths.
- Live service tests require Docker or equivalent isolated PostgreSQL, Redis,
  and MinIO services; unit tests remain service-independent.
