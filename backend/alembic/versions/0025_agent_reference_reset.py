"""One-way reset of workflow authoring and execution data for reference agents.

Workflow/task data deleted here cannot be reconstructed by downgrade. Provider,
catalog, and identity records are deliberately retained.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0025_agent_reference_reset"
down_revision: str | None = "0024_provider_runtime_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    # Discover task-owned tables from PostgreSQL's real FK metadata. Task children
    # must cascade, as in the established task model, before deleting task rows.
    task_fks = conn.execute(sa.text("""
        SELECT c.conrelid::regclass::text AS child_table, c.confdeltype::text AS delete_rule
        FROM pg_constraint c
        WHERE c.contype = 'f' AND c.confrelid = 'tasks'::regclass
    """)).mappings().all()
    non_cascading = [row["child_table"] for row in task_fks if row["delete_rule"] != "c"]
    if non_cascading:
        raise RuntimeError(f"Task dependents must cascade before reset: {non_cascading}")

    # Task-owned metadata is removed by declared ON DELETE CASCADE constraints.
    conn.execute(sa.text("DELETE FROM tasks"))
    conn.execute(sa.text("DELETE FROM activations"))
    # Include orphan drafts whose workflow_id is NULL.
    conn.execute(sa.text("DELETE FROM workflow_drafts"))
    conn.execute(sa.text("DELETE FROM workflow_versions"))
    conn.execute(sa.text("DELETE FROM workflows"))


def downgrade() -> None:
    # Workflow definitions, drafts, task history and artifacts were destroyed;
    # there is no truthful data restoration. Restore from a coordinated backup.
    pass
