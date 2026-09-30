"""Workflow publication and active version tables."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_workflows"
down_revision: str | None = "0002_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
    )
    op.create_table("workflow_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=False),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )
    op.create_table("activations",
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("workflow_versions.id"), nullable=False),
    )
    op.execute("""CREATE FUNCTION reject_workflow_version_update() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'published workflow versions are immutable'; END;
        $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER workflow_versions_immutable BEFORE UPDATE ON workflow_versions FOR EACH ROW EXECUTE FUNCTION reject_workflow_version_update()")


def downgrade() -> None:
    op.execute("DROP TRIGGER workflow_versions_immutable ON workflow_versions")
    op.execute("DROP FUNCTION reject_workflow_version_update()")
    op.drop_table("activations")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
