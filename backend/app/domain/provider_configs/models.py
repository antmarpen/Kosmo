import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# The `users` table must be registered before the string foreign keys below are
# configured. The API imports identity models through its auth routes, but the
# worker loads only this module, where an unregistered `users` table made every
# query raise NoReferencedTableError.
from app.domain.identity import models as _identity_models  # noqa: F401


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    __table_args__ = (UniqueConstraint("user_id", "provider", "visibility", "group_id",
                                       name="uq_provider_config_owner_provider_visibility_group"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    group_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # User-entered friendly name; mandatory, never defaulted to the provider type.
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    config_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    auth_ciphertext: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified", server_default="unverified")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ProviderCandidateOperation(Base):
    """Single-use encrypted payload handing candidate credentials to the worker.

    Rows live for the short candidate-discovery window only and are deleted on
    first successful consumption; expired rows are purged by the service.
    """

    __tablename__ = "provider_candidate_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
