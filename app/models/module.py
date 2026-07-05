import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Module(Base):
    __tablename__ = "modules"

    module_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.equipment_id", ondelete="SET NULL"), nullable=True, index=True
    )
    module_name: Mapped[str] = mapped_column(String(255), nullable=False)
    module_type: Mapped[str] = mapped_column(String(50), nullable=False)
    module_subtype: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    save_status: Mapped[str] = mapped_column(String(50), nullable=False, default="temporary")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
