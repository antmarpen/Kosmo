"""Track shared workflow publication revisions."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0013_pub_revision"
down_revision: str | None = "0012_workflow_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("publication_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("workflow_versions", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("workflow_versions", sa.Column("published_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_versions", "created_at")
    op.drop_column("workflow_versions", "published_by")
    op.drop_column("workflows", "publication_revision")
