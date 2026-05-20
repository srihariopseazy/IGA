"""
Pytest configuration and shared fixtures for the IGA platform test suite.

Uses an in-memory SQLite database (via aiosqlite) for unit and integration tests
so no real PostgreSQL instance is required during CI.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.utils.security import hash_password

# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# In-memory SQLite engine (shared across all tests in a session)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional session that is rolled back after each test."""
    TestSessionFactory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with TestSessionFactory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# Core tenant fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def test_tenant(db: AsyncSession):
    from backend.models.tenant import Tenant

    tenant = Tenant(
        id=uuid.uuid4(),
        name="Test Corp",
        slug="testcorp",
        status="active",
        plan="enterprise",
        max_users=500,
    )
    db.add(tenant)
    await db.flush()
    return tenant


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def test_user(db: AsyncSession, test_tenant):
    from backend.models.user import User

    user = User(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        email="testuser@testcorp.com",
        username="testuser",
        hashed_password=hash_password("TestUser123!"),
        first_name="Test",
        last_name="User",
        status="active",
        is_superadmin=False,
        is_tenant_admin=False,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture(scope="function")
async def superadmin_user(db: AsyncSession, test_tenant):
    from backend.models.user import User

    user = User(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        email="superadmin@testcorp.com",
        username="superadmin",
        hashed_password=hash_password("SuperAdmin123!"),
        first_name="Super",
        last_name="Admin",
        status="active",
        is_superadmin=True,
        is_tenant_admin=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture(scope="function")
async def tenant_admin_user(db: AsyncSession, test_tenant):
    from backend.models.user import User

    user = User(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        email="admin@testcorp.com",
        username="tenantadmin",
        hashed_password=hash_password("TenantAdmin123!"),
        first_name="Tenant",
        last_name="Admin",
        status="active",
        is_superadmin=False,
        is_tenant_admin=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# JWT auth headers helpers
# ---------------------------------------------------------------------------

def _make_headers(user_id: str, tenant_id: str, is_superadmin: bool = False) -> dict:
    from backend.utils.jwt_utils import create_access_token

    token = create_access_token(
        data={
            "sub": user_id,
            "tenant_id": tenant_id,
            "is_superadmin": is_superadmin,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def auth_headers(test_user, test_tenant):
    return _make_headers(
        str(test_user.id),
        str(test_tenant.id),
        is_superadmin=False,
    )


@pytest.fixture(scope="function")
def superadmin_headers(superadmin_user, test_tenant):
    return _make_headers(
        str(superadmin_user.id),
        str(test_tenant.id),
        is_superadmin=True,
    )


@pytest.fixture(scope="function")
def admin_headers(tenant_admin_user, test_tenant):
    return _make_headers(
        str(tenant_admin_user.id),
        str(test_tenant.id),
        is_superadmin=False,
    )


# ---------------------------------------------------------------------------
# FastAPI TestClient with DB override
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTPX async test client that injects the test DB session
    via FastAPI dependency override.
    """

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    # Mock Redis so tests don't need a real Redis instance
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.setex = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=1)
    redis_mock.incr = AsyncMock(return_value=1)
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.track_failed_login = AsyncMock(return_value=1)
    redis_mock.get_failed_logins = AsyncMock(return_value=0)
    redis_mock.blacklist_token = AsyncMock(return_value=True)
    redis_mock.is_token_blacklisted = AsyncMock(return_value=False)

    with patch("backend.utils.redis_client.redis_client", redis_mock):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper mock factories
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis():
    """Standalone Redis mock for unit tests that import redis_client directly."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    mock.track_failed_login = AsyncMock(return_value=1)
    mock.get_failed_logins = AsyncMock(return_value=0)
    mock.blacklist_token = AsyncMock(return_value=True)
    mock.is_token_blacklisted = AsyncMock(return_value=False)
    return mock


@pytest.fixture
def mock_email_service():
    mock = AsyncMock()
    mock.send_password_reset = AsyncMock(return_value=True)
    mock.send_verification_email = AsyncMock(return_value=True)
    mock.send_welcome_email = AsyncMock(return_value=True)
    return mock
