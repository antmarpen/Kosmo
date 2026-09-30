"""Identity users and rotating refresh sessions."""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0002_identity"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    roles = sa.Enum("viewer", "runner", "builder", "group_manager", "admin", name="user_role")
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("username", sa.String(120), nullable=False, unique=True), sa.Column("password_hash", sa.String(512), nullable=False), sa.Column("role", roles, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True), sa.Column("family_id", sa.String(36), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_index("ix_sessions_family_id", "sessions", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_family_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
