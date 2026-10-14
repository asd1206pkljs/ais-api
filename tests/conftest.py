import base64
import os
import shutil
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/ais_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("FILE_STORAGE_BASE_PATH", "/tmp/ais_test_files")
os.environ.setdefault("TRAIN_RESULTS_BASE_PATH", "/tmp/ais_test_train_results")
os.environ.setdefault("EQP_MODELS_BASE_PATH", "/tmp/ais_test_eqp_models")
os.environ.setdefault("DISABLE_RATE_LIMIT", "true")
# Tests talk to the ASGI app over plain "http", where httpx will not send Secure cookies.
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ENABLE_BACKGROUND_CLEANUP", "false")
os.environ.setdefault("EMAIL_BACKEND", "console")
# Multi-user security settings under test.
os.environ.setdefault("DATA_ENCRYPTION_KEY", base64.b64encode(b"\x01" * 32).decode())
os.environ.setdefault("ENCRYPT_DATA_AT_REST", "true")
os.environ.setdefault("CONSENT_REQUIRED", "true")
os.environ.setdefault("TERMS_VERSION", "2026-10-01")
os.environ.setdefault("PRIVACY_VERSION", "2026-10-01")
os.environ.setdefault("SIGNUP_REQUIRE_APPROVAL", "true")
os.environ.setdefault("SIGNUP_AUTO_APPROVE_DOMAINS", "auto.example.com")
os.environ.setdefault("CREDIT_REQUEST_AUTO_APPROVE_MAX", "0")
os.environ.setdefault("CREDIT_PURCHASE_ENABLED", "true")  # exercise the mock checkout path
os.environ.setdefault("ADMIN_EMAILS", "")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")

import app.models  # noqa: E402,F401 - register every table for create_all
from app.database import Base, get_async_session  # noqa: E402
from app.database_ddl import AUDIT_IMMUTABLE_STATEMENTS  # noqa: E402
from app.dependencies import get_db  # noqa: E402
from app.services.auth_service import create_access_token  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]
CONSENTS = {"terms_version": "2026-10-01", "privacy_version": "2026-10-01"}
PASSWORD = "password123"

# NullPool: pytest-asyncio runs the session-scoped create_tables fixture and
# function-scoped tests on different event loops; an asyncpg connection pooled
# on one loop and reused on another fails with "another operation is in progress".
engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
test_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        for statement in AUDIT_IMMUTABLE_STATEMENTS:
            await conn.execute(text(statement))
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    for path in (os.environ["FILE_STORAGE_BASE_PATH"], os.environ["TRAIN_RESULTS_BASE_PATH"],
                 os.environ["EQP_MODELS_BASE_PATH"]):
        shutil.rmtree(path, ignore_errors=True)


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


async def make_user(db_session: AsyncSession, *, role: str = "user", status: str = "active",
                    name: str = "Test User", email: str | None = None, credits: int = 0):
    from app.repositories.user_repository import UserRepository
    from app.services.auth_service import hash_password

    return await UserRepository().create(db_session, {
        "user_id": uuid.uuid4(),
        "user_name": name,
        "user_email": email or f"test_{uuid.uuid4().hex[:8]}@example.com",
        "user_password": hash_password(PASSWORD),
        "approved": True,
        "role": role,
        "status": status,
        "user_credits": credits,
    })


def bearer(user) -> dict[str, str]:
    token = create_access_token(user.user_id, user.user_email, user.token_version)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    return await make_user(db_session)


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession):
    return await make_user(db_session, name="Other User")


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    return await make_user(db_session, role="admin", name="Admin")


@pytest_asyncio.fixture
async def auth_headers(test_user):
    return bearer(test_user)


@pytest_asyncio.fixture
async def other_headers(other_user):
    return bearer(other_user)


@pytest_asyncio.fixture
async def admin_headers(admin_user):
    return bearer(admin_user)


@pytest_asyncio.fixture
async def authenticated_client(client, auth_headers):
    client.headers.update(auth_headers)
    yield client
