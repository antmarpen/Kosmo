"""Prepare provider rows for the explicit encrypted v2 conversion utility.

The migration intentionally performs no decryption and needs no application
encryption key. Existing non-v2 rows stay marked v1 until the operator runs
the conversion script; the column default remains v2 for newly-created rows.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0024_provider_runtime_v2"
down_revision: str | None = "0023_provider_runtime_format"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE provider_configs SET format = 'v1' WHERE format <> 'v2'"))
    op.alter_column("provider_configs", "format", server_default="v2")


def downgrade() -> None:
    # Converted v2 ciphertext is not reversibly convertible to the v1 file
    # contract. Never relabel rows or claim a data downgrade.
    op.alter_column("provider_configs", "format", server_default="v2")
