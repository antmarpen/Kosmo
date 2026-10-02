import uuid

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JsonType = JSON().with_variant(JSONB, "postgresql")


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    publication_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Activation(Base):
    __tablename__ = "activations"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)


class WorkflowDraft(Base):
    __tablename__ = "workflow_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    base_version_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id", ondelete="SET NULL"))
    definition: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    layout: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
