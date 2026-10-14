import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/ais_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("FILE_STORAGE_BASE_PATH", "/tmp/ais_test_files")
os.environ.setdefault("DISABLE_RATE_LIMIT", "true")
# Tests talk to the ASGI app over plain "http", where httpx will not send Secure cookies.
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ENABLE_BACKGROUND_CLEANUP", "false")

import app.models  # noqa: E402,F401 - register every table for create_all
from app.database import Base, get_async_session  # noqa: E402
from app.dependencies import get_db  # noqa: E402
from app.services.auth_service import create_access_token  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]

# NullPool: pytest-asyncio runs the session-scoped create_tables fixture and
# function-scoped tests on different event loops; an asyncpg connection pooled
# on one loop and reused on another fails with "another operation is in progress".
engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
test_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Surface unhandled errors as HTTP 500s (as a real client would see them)
    # instead of re-raising them into the test.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    from app.repositories.user_repository import UserRepository
    from app.services.auth_service import hash_password

    repo = UserRepository()
    user = await repo.create(db_session, {
        "user_id": uuid.uuid4(),
        "user_name": "Test User",
        "user_email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "user_password": hash_password("password123"),
        "approved": True,
    })
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user):
    token = create_access_token(
        test_user.user_id, test_user.user_email, test_user.token_version
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def authenticated_client(client, auth_headers):
    client.headers.update(auth_headers)
    yield client
