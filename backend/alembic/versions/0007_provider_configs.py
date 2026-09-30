"""Store encrypted per-user runtime provider configuration."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_provider_configs"
down_revision: str | None = "0006_capacity_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("config_ciphertext", sa.Text(), nullable=False),
        sa.Column("auth_ciphertext", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_provider_config_user_provider"),
    )
    op.create_index("ix_provider_configs_user_id", "provider_configs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_provider_configs_user_id", table_name="provider_configs")
    op.drop_table("provider_configs")
