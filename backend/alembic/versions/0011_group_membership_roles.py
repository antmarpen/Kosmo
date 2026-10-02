"""Add roles to group memberships."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011_group_membership_roles"
down_revision: str | None = "0010_provider_config_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role_type = sa.Enum("member", "group_manager", name="group_membership_role")
    role_type.create(op.get_bind(), checkfirst=True)
    op.add_column("group_memberships", sa.Column("role", role_type, nullable=False, server_default="member"))


def downgrade() -> None:
    op.drop_column("group_memberships", "role")
    sa.Enum(name="group_membership_role").drop(op.get_bind(), checkfirst=True)
