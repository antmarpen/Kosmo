import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domain.identity import models as _identity_models  # noqa: F401


class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        CheckConstraint("visibility IN ('personal', 'group', 'global')", name="ck_mcp_servers_visibility"),
        CheckConstraint("(visibility = 'group') = (group_id IS NOT NULL)", name="ck_mcp_servers_group_scope"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 80", name="ck_mcp_servers_name_length"),
        CheckConstraint("transport_type IN ('stdio', 'http')", name="ck_mcp_servers_transport"),
        Index("uq_mcp_servers_personal_name_ci", "owner_user_id", text("lower(name)"), unique=True,
              postgresql_where=text("visibility = 'personal'")),
        Index("uq_mcp_servers_group_name_ci", "owner_user_id", "group_id", text("lower(name)"), unique=True,
              postgresql_where=text("visibility = 'group'")),
        Index("uq_mcp_servers_global_name_ci", "owner_user_id", text("lower(name)"), unique=True,
              postgresql_where=text("visibility = 'global'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    group_id: Mapped[str | None] = mapped_column(String(36))
    transport_type: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_config: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    secret_ciphertext: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
