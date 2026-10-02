"""Record candidate operation purpose and verification success state."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0018_candidate_operation_purpose"
down_revision: str | None = "0017_provider_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows were discovery hand-offs (verification rows never survived
    # to a save before this change), so both backfills are safe defaults.
    op.add_column("provider_candidate_operations",
                  sa.Column("purpose", sa.String(16), nullable=False,
                            server_default="discovery"))
    op.add_column("provider_candidate_operations",
                  sa.Column("verification_succeeded", sa.Boolean(), nullable=False,
                            server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("provider_candidate_operations", "verification_succeeded")
    op.drop_column("provider_candidate_operations", "purpose")
