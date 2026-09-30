"""Add global task and agent capacity claims."""
from alembic import op
import sqlalchemy as sa

revision = "0006_capacity_claims"
down_revision = "0005_task_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "capacity_claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "kind", name="uq_capacity_claim_task_kind"),
    )
    op.create_index("ix_capacity_claims_kind", "capacity_claims", ["kind"])


def downgrade():
    op.drop_index("ix_capacity_claims_kind", table_name="capacity_claims")
    op.drop_table("capacity_claims")
