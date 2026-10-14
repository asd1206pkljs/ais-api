import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness applies only to verified accounts, so an
        # unverified sign-up can never lock the real owner of an email out.
        Index(
            "uq_users_user_email_lower_approved",
            text("lower(user_email)"),
            unique=True,
            postgresql_where=text("approved"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Not unique on its own: several unverified sign-ups may share an email
    # (see uq_users_user_email_lower_approved above).
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_password: Mapped[str] = mapped_column(String(255), nullable=False)
    user_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True once the user has clicked the verification link sent at sign-up.
    approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Platform-wide role (UserRole). Group-level roles live in group_members.
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="user", server_default=text("'user'")
    )
    # Account lifecycle after verification (UserStatus): pending_approval |
    # active | disabled. Only `active` accounts may sign in.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_approval",
        server_default=text("'pending_approval'"),
    )
    # Embedded in every access token as `ver`; bumping it invalidates all of
    # the user's outstanding tokens (password change / reset).
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
