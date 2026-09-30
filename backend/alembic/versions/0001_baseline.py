"""Empty baseline (schema arrives with WP-05+).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-30

"""
from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline: no tables yet; marks the start of the migration history."""


def downgrade() -> None:
    """Nothing to downgrade from the empty baseline."""
