"""Migration wiring tests that do not require a running service."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).parents[2]


def test_alembic_has_a_runtime_foundation_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0001_runtime_foundation"]
    assert (ROOT / "alembic" / "env.py").exists()
