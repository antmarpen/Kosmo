import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    __table_args__ = (UniqueConstraint("user_id", "provider", "visibility", "group_id",
                                       name="uq_provider_config_owner_provider_visibility_group"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    group_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    config_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    auth_ciphertext: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
