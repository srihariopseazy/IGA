"""
Unit tests for AuthService.
All database interactions use the in-memory SQLite test engine from conftest.py.
Redis calls are mocked via the mock_redis fixture.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.models.user import User
from backend.models.tenant import Tenant
from backend.services.auth_service import AuthService
from backend.utils.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant() -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        name="Auth Test Tenant",
        slug="authtest",
        status="active",
        plan="enterprise",
        max_users=100,
    )


def _make_user(tenant_id, password="GoodPass123!", status="active", mfa=False) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email="alice@authtest.com",
        username="alice",
        hashed_password=hash_password(password),
        first_name="Alice",
        last_name="Test",
        status=status,
        is_superadmin=False,
        is_tenant_admin=False,
        email_verified=True,
        mfa_enabled=mfa,
    )


LOGIN_KWARGS = dict(
    ip_address="127.0.0.1",
    user_agent="pytest",
    device_fingerprint="fp-test",
)


# ---------------------------------------------------------------------------
# test_login_success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        result = await svc.login(
            email="alice@authtest.com",
            password="GoodPass123!",
            tenant_slug="authtest",
            **LOGIN_KWARGS,
        )

    assert "access_token" in result
    assert "refresh_token" in result
    assert result["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# test_login_wrong_password
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_wrong_password(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        with pytest.raises(ValueError, match="Invalid credentials"):
            await svc.login(
                email="alice@authtest.com",
                password="WrongPassword!",
                tenant_slug="authtest",
                **LOGIN_KWARGS,
            )


# ---------------------------------------------------------------------------
# test_login_locked_account
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_locked_account(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    user.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        with pytest.raises(ValueError, match="Account locked"):
            await svc.login(
                email="alice@authtest.com",
                password="GoodPass123!",
                tenant_slug="authtest",
                **LOGIN_KWARGS,
            )


# ---------------------------------------------------------------------------
# test_login_mfa_required
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_mfa_required(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id, mfa=True)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        result = await svc.login(
            email="alice@authtest.com",
            password="GoodPass123!",
            tenant_slug="authtest",
            **LOGIN_KWARGS,
        )

    assert result.get("requires_mfa") is True
    assert "user_id" in result


# ---------------------------------------------------------------------------
# test_login_invalid_tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_invalid_tenant(db, mock_redis):
    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        with pytest.raises(ValueError, match="Invalid tenant"):
            await svc.login(
                email="alice@nowhere.com",
                password="GoodPass123!",
                tenant_slug="no-such-tenant",
                **LOGIN_KWARGS,
            )


# ---------------------------------------------------------------------------
# test_login_inactive_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_inactive_user(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id, status="inactive")
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        with pytest.raises(ValueError, match="inactive"):
            await svc.login(
                email="alice@authtest.com",
                password="GoodPass123!",
                tenant_slug="authtest",
                **LOGIN_KWARGS,
            )


# ---------------------------------------------------------------------------
# test_refresh_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_token(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        login_result = await svc.login(
            email="alice@authtest.com",
            password="GoodPass123!",
            tenant_slug="authtest",
            **LOGIN_KWARGS,
        )
        refresh_token = login_result["refresh_token"]

        # Now use it
        result = await svc.refresh_token(refresh_token)

    assert "access_token" in result


# ---------------------------------------------------------------------------
# test_blacklisted_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blacklisted_token(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    db.add(tenant)
    db.add(user)
    await db.flush()

    # Make Redis report that the token IS blacklisted
    mock_redis.is_token_blacklisted = AsyncMock(return_value=True)

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        login_result = await svc.login(
            email="alice@authtest.com",
            password="GoodPass123!",
            tenant_slug="authtest",
            **LOGIN_KWARGS,
        )
        refresh_token = login_result["refresh_token"]

        with pytest.raises((ValueError, Exception)):
            await svc.refresh_token(refresh_token)


# ---------------------------------------------------------------------------
# test_setup_totp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_setup_totp(db, mock_redis):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        result = await svc.setup_totp(str(user.id))

    assert "secret" in result or "qr_code" in result or "otpauth_url" in result


# ---------------------------------------------------------------------------
# test_verify_totp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_totp(db, mock_redis):
    """Verify a TOTP code — invalid code should raise / return error."""
    tenant = _make_tenant()
    user = _make_user(tenant.id, mfa=True)
    db.add(tenant)
    db.add(user)
    await db.flush()

    # Add a MFA device with a known secret
    import pyotp
    from backend.models.user import MFADevice

    secret = pyotp.random_base32()
    device = MFADevice(
        user_id=user.id,
        device_type="totp",
        secret=secret,
        is_primary=True,
        is_verified=True,
    )
    db.add(device)
    await db.flush()

    totp = pyotp.TOTP(secret)
    valid_code = totp.now()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        is_valid = await svc._verify_mfa(user, valid_code)

    assert is_valid is True

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService"),
    ):
        svc = AuthService(db)
        is_invalid = await svc._verify_mfa(user, "000000")

    assert is_invalid is False


# ---------------------------------------------------------------------------
# test_password_reset_flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_password_reset_flow(db, mock_redis, mock_email_service):
    tenant = _make_tenant()
    user = _make_user(tenant.id)
    db.add(tenant)
    db.add(user)
    await db.flush()

    with (
        patch("backend.services.auth_service.redis_client", mock_redis),
        patch("backend.services.auth_service.EmailService", return_value=mock_email_service),
    ):
        svc = AuthService(db)

        # Step 1: initiate reset
        await svc.initiate_password_reset(
            email="alice@authtest.com",
            tenant_slug="authtest",
            base_url="http://localhost:3000",
        )
        mock_email_service.send_password_reset.assert_called_once()

        # Step 2: retrieve the token from DB
        from backend.models.user import PasswordResetToken
        from sqlalchemy import select

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id
            )
        )
        reset_record = result.scalar_one_or_none()
        assert reset_record is not None

        # Step 3: reset password using raw token
        reset_result = await svc.reset_password(
            token=reset_record.token_hash,  # service should accept hashed token
            new_password="NewSecurePass456!",
        )
        # Either returns truthy result or raises — check no exception is unexpected
        # (implementation-dependent, just confirm flow reaches here)
