"""Add a mandatory user-entered display name to provider configurations."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0017_provider_display_name"
down_revision: str | None = "0016_drop_selected_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are backfilled once from the provider type; the column then
    # becomes NOT NULL without any default, so every future row must carry a
    # user-entered name.
    op.add_column("provider_configs", sa.Column("display_name", sa.String(80), nullable=True))
    op.execute("UPDATE provider_configs SET display_name = provider")
    op.alter_column("provider_configs", "display_name", existing_type=sa.String(80), nullable=False)


def downgrade() -> None:
    op.drop_column("provider_configs", "display_name")
