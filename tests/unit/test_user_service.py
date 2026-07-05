import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import hash_password
from app.services.user_service import UserService


def _make_user(**kwargs) -> User:
    defaults = {
        "user_id": uuid.uuid4(),
        "user_name": "Test User",
        "user_email": "test@example.com",
        "user_password": hash_password("password123"),
        "user_credits": 0,
        "joined_at": None,
        "last_login_at": None,
    }
    defaults.update(kwargs)
    user = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(repo):
    return UserService(repo)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_register_success(service, repo, session):
    repo.find_by_email.return_value = None
    user = _make_user()
    repo.create.return_value = user
    result = await service.register(session, UserCreate(
        user_name="Test", user_email="test@example.com", user_password="Password123!"
    ))
    assert result.user_email == "test@example.com"
    repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_register_duplicate_email(service, repo, session):
    repo.find_by_email.return_value = _make_user()
    with pytest.raises(ConflictError):
        await service.register(session, UserCreate(
            user_name="Test", user_email="test@example.com", user_password="Password123!"
        ))


@pytest.mark.asyncio
async def test_authenticate_success(service, repo, session):
    user = _make_user()
    repo.find_by_email.return_value = user
    repo.update.return_value = user
    repo.find_by_id.return_value = user
    result = await service.authenticate(session, "test@example.com", "password123")
    assert result.user_email == "test@example.com"


@pytest.mark.asyncio
async def test_authenticate_wrong_password(service, repo, session):
    user = _make_user()
    repo.find_by_email.return_value = user
    with pytest.raises(AuthenticationError):
        await service.authenticate(session, "test@example.com", "wrongpassword")


@pytest.mark.asyncio
async def test_authenticate_user_not_found(service, repo, session):
    repo.find_by_email.return_value = None
    with pytest.raises(AuthenticationError):
        await service.authenticate(session, "nobody@example.com", "password123")


@pytest.mark.asyncio
async def test_get_by_id_not_found(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_by_id(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_update_hashes_password(service, repo, session):
    user = _make_user()
    repo.update.return_value = user
    await service.update(session, user.user_id, UserUpdate(user_password="NewPassword123!"))
    call_kwargs = repo.update.call_args[0][2]
    assert call_kwargs["user_password"] != "NewPassword123!"
    assert call_kwargs["user_password"].startswith("$2b$")
