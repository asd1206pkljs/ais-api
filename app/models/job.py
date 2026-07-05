import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.enums import JobStatus


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    simulator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_status: Mapped[str] = mapped_column(String(50), nullable=False, default=JobStatus.PENDING)
    viewers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    result_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
