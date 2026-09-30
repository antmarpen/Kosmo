"""Persist task and node state events for SSE replay."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_task_events"
down_revision: str | None = "0004_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(200)),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_events_task_id_id", "task_events", ["task_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_task_events_task_id_id", table_name="task_events")
    op.drop_table("task_events")
