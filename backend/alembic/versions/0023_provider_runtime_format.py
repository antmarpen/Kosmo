"""Mark encrypted provider runtime files with their on-disk format."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0023_provider_runtime_format"
down_revision: str | None = "0022_agent_catalogs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("format", sa.String(length=8), nullable=False, server_default="v1"),
    )
    op.alter_column("provider_configs", "format", server_default="v2")


def downgrade() -> None:
    op.drop_column("provider_configs", "format")
