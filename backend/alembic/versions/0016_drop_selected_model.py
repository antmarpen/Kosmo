"""Stop storing a model in provider configurations."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0016_drop_selected_model"
down_revision: str | None = "0015_candidate_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("provider_configs", "selected_model")


def downgrade() -> None:
    op.add_column("provider_configs", sa.Column("selected_model", sa.String(300), nullable=True))
