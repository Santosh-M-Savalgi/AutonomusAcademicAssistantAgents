"""Bootstrap the Phase 1 migration history without domain tables."""

from collections.abc import Sequence

from alembic import op


revision: str = "0001_runtime_foundation"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Establish a clean migration head for later domain migrations."""

    pass


def downgrade() -> None:
    """Remove the no-op runtime foundation revision."""

    pass
