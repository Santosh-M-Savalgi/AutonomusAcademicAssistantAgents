# Alembic migrations

This migration tree is intentionally empty of domain tables in Sprint 1.1. The initial
revision establishes a migration head so later foundation and domain migrations can be
added without resurrecting the deleted v2 schema.

The database URL is loaded by `apps.api.config.Settings` from environment variables or
`.env`; run `make migrate` after `make up`.
