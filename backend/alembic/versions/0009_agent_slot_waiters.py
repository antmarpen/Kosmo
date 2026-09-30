"""Persist FIFO order for tasks waiting on agent capacity."""
from alembic import op
import sqlalchemy as sa

revision = "0009_agent_slot_waiters"
down_revision = "0008_artifact_output_unique"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_slot_waiters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_agent_slot_waiter_task"),
    )
    op.create_index("ix_agent_slot_waiters_order", "agent_slot_waiters", ["id"])


def downgrade():
    op.drop_index("ix_agent_slot_waiters_order", table_name="agent_slot_waiters")
    op.drop_table("agent_slot_waiters")
