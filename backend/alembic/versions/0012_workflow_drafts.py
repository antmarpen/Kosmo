"""Add per-user workflow drafts."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_workflow_drafts"
down_revision: str | None = "0011_group_membership_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_version_id", sa.String(36), sa.ForeignKey("workflow_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("layout", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_drafts_author_id", "workflow_drafts", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_drafts_author_id", table_name="workflow_drafts")
    op.drop_table("workflow_drafts")
