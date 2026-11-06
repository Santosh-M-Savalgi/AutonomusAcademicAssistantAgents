# Sprint 2.5.1: Review lifecycle hardening

## Objective

Harden Sprint 2.5 review creation, editing and confirmation at concurrency and
validation boundaries before starting Sprint 2.6.

## Changes

- Concurrent begin-review requests now return the one committed review and
  revision instead of leaking a uniqueness error or returning an uncommitted
  caller-local snapshot.
- Concurrent confirmation requests for the same revision are idempotent even
  when both requests pass their initial read before either final lock.
- Source-derived elements cannot be relabeled as `HUMAN` or rewrite their
  stable key, origin or parse confidence during review.
- Invalid review snapshots, including hierarchy and provenance violations, are
  translated to typed `422` API errors and do not create revision rows.
- Added unit and disposable live integration coverage for all of the above.
- No schema or dependency changes were required.

## Verification on 2026-10-03

| Check | Result |
|---|---|
| `make test` | **183 passed, 69 skipped**, 1 expected Starlette/AnyIO warning |
| `make check` | Ruff passed; package Mypy passed on 35 files; import contracts 5 kept/0 broken; pytest **183 passed, 69 skipped** |
| `make integration` | **70 passed**, 1 expected Starlette/AnyIO warning |
| Review unit suite | **12 passed**, 1 expected warning |
| Review live suite | **10 passed**, 1 expected warning |
| `uv run --locked --group dev mypy --strict packages apps/worker` | **Success**, no issues in 44 source files |
| Compose config validation | Passed for mock and worker profiles |
| Git safety checks | `git diff --check` passed; nothing staged |

Sprint 2.6 is ready to begin. No commit was created.
