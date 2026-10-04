import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, false, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# The `users` table must be registered before the string foreign keys below are
# configured. The API imports identity models through its auth routes, but the
# worker loads only this module, where an unregistered `users` table made every
# query raise NoReferencedTableError.
from app.domain.identity import models as _identity_models  # noqa: F401


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    # Multiple named instances per owner and provider may coexist in the same
    # scope; the invariant is a case-insensitive display name unique per owner
    # and provider (functional unique index; see migration 0019).
    __table_args__ = (
        Index("uq_provider_config_owner_provider_name_ci", "user_id", "provider",
              func.lower(text("display_name")), unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    group_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # User-entered friendly name; mandatory, never defaulted to the provider type.
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    config_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    auth_ciphertext: Mapped[str | None] = mapped_column(Text)
    # v1 rows are marked by the additive 0023 migration; new writes use v2.
    format: Mapped[str] = mapped_column(String(8), nullable=False, default="v2", server_default="v2")
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified", server_default="unverified")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ProviderCandidateOperation(Base):
    """Single-use encrypted payload handing candidate credentials to the worker.

    Rows live for the short candidate-discovery window only and are deleted on
    first successful consumption; expired rows are purged by the service.
    `purpose` records whether the operation hands credentials to a discovery
    or a verification container run, and `verification_succeeded` records a
    completed successful verification: only verification-purpose rows with
    that flag can be redeemed as single-use proof at save time.
    """

    __tablename__ = "provider_candidate_operations"

    PURPOSE_DISCOVERY = "discovery"
    PURPOSE_VERIFICATION = "verification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False,
                                         default=PURPOSE_DISCOVERY, server_default=PURPOSE_DISCOVERY)
    verification_succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                         default=False, server_default=false())
