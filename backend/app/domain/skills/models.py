import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domain.identity import models as _identity_models  # noqa: F401


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint("visibility IN ('personal', 'group', 'global')", name="ck_skills_visibility"),
        CheckConstraint("(visibility = 'group') = (group_id IS NOT NULL)", name="ck_skills_group_scope"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 80", name="ck_skills_name_length"),
        CheckConstraint("length(description) <= 2000", name="ck_skills_description_length"),
        CheckConstraint("length(instructions) <= 100000", name="ck_skills_instructions_length"),
        Index("uq_skills_personal_name_ci", "owner_user_id", text("lower(name)"), unique=True,
              postgresql_where=text("visibility = 'personal'")),
        Index("uq_skills_group_name_ci", "owner_user_id", "group_id", text("lower(name)"), unique=True,
              postgresql_where=text("visibility = 'group'")),
        Index("uq_skills_global_name_ci", "owner_user_id", text("lower(name)"), unique=True,
              postgresql_where=text("visibility = 'global'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    group_id: Mapped[str | None] = mapped_column(String(36))
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
