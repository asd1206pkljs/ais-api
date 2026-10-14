import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import RequestStatus
from app.models.user import User
from app.models.user_request import UserRequest


class UserRequestRepository:
    async def create(self, session: AsyncSession, data: dict) -> UserRequest:
        row = UserRequest(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def find_by_id(self, session: AsyncSession, request_id: uuid.UUID) -> UserRequest | None:
        result = await session.execute(select(UserRequest).where(UserRequest.request_id == request_id))
        return result.scalar_one_or_none()

    async def update(self, session: AsyncSession, request_id: uuid.UUID, data: dict) -> UserRequest | None:
        """Caller commits, so a decision and its side effects land together."""
        row = await self.find_by_id(session, request_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await session.flush()
        return row

    async def transition(
        self, session: AsyncSession, request_id: uuid.UUID, from_status: str, data: dict
    ) -> UserRequest | None:
        """Apply `data` only if the request is still in `from_status` (so two
        admins cannot both approve). Returns the row or None. Caller commits."""
        result = await session.execute(
            update(UserRequest)
            .where(UserRequest.request_id == request_id, UserRequest.status == from_status)
            .values(**data)
            .returning(UserRequest)
        )
        return result.scalar_one_or_none()

    async def find_pending(
        self, session: AsyncSession, user_id: uuid.UUID, request_type: str
    ) -> UserRequest | None:
        result = await session.execute(
            select(UserRequest).where(
                UserRequest.user_id == user_id,
                UserRequest.request_type == request_type,
                UserRequest.status == RequestStatus.PENDING.value,
            )
        )
        return result.scalars().first()

    async def has_auto_approved_since(
        self, session: AsyncSession, user_id: uuid.UUID, request_type: str, since: datetime
    ) -> bool:
        result = await session.execute(
            select(UserRequest.request_id)
            .where(
                UserRequest.user_id == user_id,
                UserRequest.request_type == request_type,
                UserRequest.status == RequestStatus.AUTO_APPROVED.value,
                UserRequest.created_at >= since,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _filters(user_id, status, request_type) -> list:
        conditions = []
        if user_id is not None:
            conditions.append(UserRequest.user_id == user_id)
        if status:
            conditions.append(UserRequest.status == status)
        if request_type:
            conditions.append(UserRequest.request_type == request_type)
        return conditions

    async def list_with_user(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        request_type: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[tuple[UserRequest, str, str]]:
        """(request, user_email, user_name) newest first."""
        result = await session.execute(
            select(UserRequest, User.user_email, User.user_name)
            .join(User, User.user_id == UserRequest.user_id)
            .where(*self._filters(user_id, status, request_type))
            .order_by(UserRequest.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def count(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        request_type: str | None = None,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(UserRequest)
            .where(*self._filters(user_id, status, request_type))
        )
        return result.scalar_one()
