"""Task submission, state, notes, executions, and artifact metadata."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_tasks"
down_revision: str | None = "0003_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table("tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False), sa.Column("prompt", sa.String()),
        sa.Column("input_values", json_type, nullable=False), sa.Column("resolved_definition", json_type, nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    op.create_table("task_notes", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("message_key", sa.String(200), nullable=False),
        sa.Column("params", json_type, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "revision", name="uq_task_note_revision"))
    op.create_table("node_executions", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(200), nullable=False), sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("state", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("error", json_type))
    op.create_table("artifacts", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(200), nullable=False), sa.Column("logical_name", sa.String(500), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(200), nullable=False), sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("storage_path", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("node_executions")
    op.drop_table("task_notes")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_table("tasks")
