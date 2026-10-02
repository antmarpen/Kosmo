"""Persist selected provider model and verification state."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0014_provider_model"
down_revision: str | None = "0013_pub_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("provider_configs", sa.Column("selected_model", sa.String(300), nullable=True))
    op.add_column("provider_configs", sa.Column("verification_status", sa.String(16), nullable=False, server_default="unverified"))


def downgrade() -> None:
    op.drop_column("provider_configs", "verification_status")
    op.drop_column("provider_configs", "selected_model")
