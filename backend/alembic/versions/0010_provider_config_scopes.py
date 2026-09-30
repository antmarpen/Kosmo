"""Add visibility scopes and group membership storage."""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0010_provider_config_scopes"
down_revision: str | None = "0009_agent_slot_waiters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table("groups", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("name", sa.String(120), unique=True, nullable=False))
    op.create_table("group_memberships",
        sa.Column("group_id", sa.String(36), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))
    op.add_column("provider_configs", sa.Column("visibility", sa.String(16), nullable=False, server_default="personal"))
    op.add_column("provider_configs", sa.Column("group_id", sa.String(36), sa.ForeignKey("groups.id", ondelete="CASCADE")))
    op.drop_constraint("uq_provider_config_user_provider", "provider_configs", type_="unique")
    op.create_unique_constraint("uq_provider_config_owner_provider_visibility_group",
                                "provider_configs", ["user_id", "provider", "visibility", "group_id"])
    op.create_index("ix_provider_configs_group_id", "provider_configs", ["group_id"])
    op.create_index("uq_provider_configs_global_provider", "provider_configs", ["provider"], unique=True,
                    postgresql_where=sa.text("visibility = 'global'"))
    op.create_index("uq_provider_configs_group_provider", "provider_configs", ["group_id", "provider"], unique=True,
                    postgresql_where=sa.text("visibility = 'group'"))

def downgrade() -> None:
    op.drop_index("uq_provider_configs_group_provider", table_name="provider_configs")
    op.drop_index("uq_provider_configs_global_provider", table_name="provider_configs")
    op.drop_index("ix_provider_configs_group_id", table_name="provider_configs")
    op.drop_constraint("uq_provider_config_owner_provider_visibility_group", "provider_configs", type_="unique")
    op.create_unique_constraint("uq_provider_config_user_provider", "provider_configs", ["user_id", "provider"])
    op.drop_column("provider_configs", "group_id")
    op.drop_column("provider_configs", "visibility")
    op.drop_table("group_memberships")
    op.drop_table("groups")
