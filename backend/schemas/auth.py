from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    tenant_slug: str = Field(min_length=1, max_length=63)
    device_fingerprint: Optional[str] = None
    mfa_code: Optional[str] = Field(default=None, min_length=6, max_length=8)


class UserInfo(BaseModel):
    id: uuid.UUID
    email: str
    username: Optional[str] = None
    first_name: str
    last_name: str
    full_name: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    tenant_id: uuid.UUID
    mfa_enabled: bool = False
    avatar_url: Optional[str] = None
    is_active: bool = True
    last_login: Optional[datetime] = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry
    user: UserInfo
    mfa_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    tenant_slug: str = Field(min_length=1, max_length=63)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class MagicLinkRequest(BaseModel):
    email: EmailStr
    tenant_slug: str = Field(min_length=1, max_length=63)


class MagicLinkResponse(BaseModel):
    message: str = "Magic link sent if the email exists in our system"


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class MFASetupResponse(BaseModel):
    secret: str
    qr_code_url: str
    backup_codes: List[str]


class MFAVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)
    device_id: Optional[str] = None


class MFAVerifyResponse(BaseModel):
    verified: bool
    backup_code_used: bool = False


class TokenData(BaseModel):
    """Parsed JWT claims attached to request.state."""
    sub: str  # user_id
    tenant_id: str
    email: str
    roles: List[str] = Field(default_factory=list)
    jti: str
    exp: int
    iat: Optional[int] = None
    type: str = "access"


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class VerifyEmailRequest(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v
