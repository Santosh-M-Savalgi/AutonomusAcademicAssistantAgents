.PHONY: up down migrate test unit integration check llama-help llama-up

AAA_PROFILE ?= mock

up:
	docker compose --profile $(AAA_PROFILE) up -d --build

down:
	docker compose down --remove-orphans

migrate:
	uv run --locked alembic upgrade head

test:
	uv run --locked --group dev pytest tests/unit tests/integration

unit:
	uv run --locked --group dev pytest tests/unit

integration:
	AAA_RUN_SERVICE_INTEGRATION=1 uv run --locked --group dev pytest tests/integration

check:
	uv run --locked --group dev ruff check .
	uv run --locked --group dev mypy --strict packages
	uv run --locked --group dev lint-imports
	uv run --locked --group dev pytest

llama-help:
	uv run --locked python -m packages.model_client.llama_server help --profile $(if $(filter gpu,$(AAA_PROFILE)),gpu,cpu)

llama-up:
	@test "$(AAA_PROFILE)" = cpu || test "$(AAA_PROFILE)" = gpu || (echo "AAA_PROFILE must be cpu or gpu for llama-up" >&2; exit 2)
	uv run --locked python -m packages.model_client.llama_server serve --profile $(AAA_PROFILE)
