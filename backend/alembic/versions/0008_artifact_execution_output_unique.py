"""Make artifact output persistence idempotent per execution."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_artifact_output_unique"
down_revision: str | None = "0007_provider_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_artifact_execution_output", "artifacts",
        ["task_id", "node_id", "logical_name", "iteration", "attempt"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifact_execution_output", "artifacts", type_="unique")
