"""Store short-lived single-use candidate provider operations."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0015_candidate_operations"
down_revision: str | None = "0014_provider_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_candidate_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_candidate_operations_user_id", "provider_candidate_operations", ["user_id"])
    op.create_index("ix_provider_candidate_operations_expires_at", "provider_candidate_operations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_candidate_operations_expires_at", table_name="provider_candidate_operations")
    op.drop_index("ix_provider_candidate_operations_user_id", table_name="provider_candidate_operations")
    op.drop_table("provider_candidate_operations")
