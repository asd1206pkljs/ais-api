import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FlowRecipe(Base):
    __tablename__ = "flow_recipes"

    flow_recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    flow_recipe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    flow_recipe_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    save_status: Mapped[str] = mapped_column(String(50), nullable=False, default="temporary")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
