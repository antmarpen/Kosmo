"""Additive persistence for agent, MCP server, and skill catalogs."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0022_agent_catalogs"
down_revision: str | None = "0021_editor_contract_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table(name, extra):
    return op.create_table(
        name,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("group_id", sa.String(36)),
        *extra,
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("visibility IN ('personal', 'group', 'global')", name=f"ck_{name}_visibility"),
        sa.CheckConstraint("(visibility = 'group') = (group_id IS NOT NULL)", name=f"ck_{name}_group_scope"),
        sa.CheckConstraint("length(btrim(name)) BETWEEN 1 AND 80", name=f"ck_{name}_name_length"),
    )


def _indexes(name):
    op.create_index(f"uq_{name}_personal_name_ci", name, ["owner_user_id", sa.text("lower(name)")], unique=True,
                    postgresql_where=sa.text("visibility = 'personal'"))
    op.create_index(f"uq_{name}_group_name_ci", name, ["owner_user_id", "group_id", sa.text("lower(name)")], unique=True,
                    postgresql_where=sa.text("visibility = 'group'"))
    op.create_index(f"uq_{name}_global_name_ci", name, ["owner_user_id", sa.text("lower(name)")], unique=True,
                    postgresql_where=sa.text("visibility = 'global'"))


def upgrade() -> None:
    _table("agents", [
        sa.Column("runtime", sa.String(32), nullable=False, server_default="opencode"),
        sa.Column("model", sa.String(300), nullable=False), sa.Column("reasoning_effort", sa.String(80)),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("mcp_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("skill_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
    ])
    op.create_check_constraint("ck_agents_runtime", "agents", "runtime = 'opencode'")
    _table("skills", [
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
    ])
    op.create_check_constraint("ck_skills_description_length", "skills", "length(description) <= 2000")
    op.create_check_constraint("ck_skills_instructions_length", "skills", "length(instructions) <= 100000")
    _table("mcp_servers", [
        sa.Column("transport_type", sa.String(16), nullable=False),
        sa.Column("safe_config", postgresql.JSONB(), nullable=False),
        sa.Column("secret_ciphertext", postgresql.JSONB(), nullable=False, server_default="{}"),
    ])
    op.create_check_constraint("ck_mcp_servers_transport", "mcp_servers", "transport_type IN ('stdio', 'http')")
    for table in ("agents", "skills", "mcp_servers"):
        _indexes(table)


def downgrade() -> None:
    for table in ("mcp_servers", "skills", "agents"):
        op.drop_table(table)
