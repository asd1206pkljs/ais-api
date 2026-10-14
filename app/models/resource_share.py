import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResourceShare(Base):
    """A grant of `permission` on one resource to one principal.

    principal_type/principal_id: ("user", <user uuid>), ("group", <group uuid>)
    or ("public", "*"). resource_id is stored as text so that uuid-keyed and
    integer-keyed resources share one table.
    """

    __tablename__ = "resource_shares"
    __table_args__ = (
        UniqueConstraint(
            "resource_type", "resource_id", "principal_type", "principal_id",
            name="uq_resource_shares_principal",
        ),
        Index("ix_resource_shares_resource", "resource_type", "resource_id"),
        Index("ix_resource_shares_principal", "principal_type", "principal_id"),
    )

    share_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
