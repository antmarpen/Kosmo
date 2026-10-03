"""Delete workflows whose stored definitions use the removed editor contract.

This is an intentionally destructive, one-way cleanup. Database task rows are
deleted before workflows because tasks.workflow_id has no ON DELETE action;
task-owned rows then use their declared ON DELETE CASCADE constraints.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0021_editor_contract_cleanup"
down_revision: str | None = "0020_workflow_name_ci"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    # Freeze the legacy contract in this migration. Definitions are JSONB; the
    # serialized key check intentionally does not depend on mutable app code.
    deprecated = "definition::text LIKE '%\"label_message_key\"%'"
    conn.execute(sa.text(f"""
        CREATE TEMP TABLE deprecated_workflow_ids ON COMMIT DROP AS
        SELECT workflow_id FROM workflow_versions WHERE {deprecated}
        UNION
        SELECT workflow_id FROM workflow_drafts
          WHERE workflow_id IS NOT NULL AND {deprecated}
        UNION
        SELECT workflow_id FROM tasks WHERE resolved_definition::text LIKE '%"label_message_key"%'
    """))
    # workflow_id deliberately has no cascade from workflows to tasks.
    conn.execute(sa.text("""
        DELETE FROM tasks WHERE workflow_id IN (SELECT workflow_id FROM deprecated_workflow_ids)
    """))
    conn.execute(sa.text("""
        DELETE FROM activations WHERE workflow_id IN (SELECT workflow_id FROM deprecated_workflow_ids)
    """))
    conn.execute(sa.text("""
        DELETE FROM workflow_drafts WHERE workflow_id IN (SELECT workflow_id FROM deprecated_workflow_ids)
    """))
    conn.execute(sa.text("""
        DELETE FROM workflow_versions WHERE workflow_id IN (SELECT workflow_id FROM deprecated_workflow_ids)
    """))
    conn.execute(sa.text("""
        DELETE FROM workflows WHERE id IN (SELECT workflow_id FROM deprecated_workflow_ids)
    """))


def downgrade() -> None:
    # Deleted application data cannot be reconstructed; downgrade is a no-op.
    pass
