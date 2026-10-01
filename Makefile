.PHONY: up down migrate test check

AAA_PROFILE ?= mock

up:
	docker compose --profile $(AAA_PROFILE) up -d --build

down:
	docker compose down --remove-orphans

migrate:
	uv run alembic upgrade head

test:
	uv run --group dev pytest tests/unit tests/integration

check:
	uv run --group dev ruff check .
	uv run --group dev mypy --strict packages
	uv run --group dev lint-imports
	uv run --group dev pytest
