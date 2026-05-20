from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    username: Optional[str] = Field(default=None, max_length=150)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    department_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    job_title: Optional[str] = Field(default=None, max_length=200)
    employee_id: Optional[str] = Field(default=None, max_length=100)
    hire_date: Optional[datetime] = None
    temporary_password: Optional[str] = Field(default=None, min_length=12, max_length=128)
    send_welcome_email: bool = True
    role_ids: List[uuid.UUID] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    department_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    job_title: Optional[str] = Field(default=None, max_length=200)
    employee_id: Optional[str] = Field(default=None, max_length=100)
    hire_date: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class UserProfileUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    job_title: Optional[str] = Field(default=None, max_length=200)
    timezone: Optional[str] = Field(default=None, max_length=50)
    locale: Optional[str] = Field(default=None, max_length=20)
    notification_preferences: Optional[Dict[str, Any]] = None


class UserStatusUpdate(BaseModel):
    status: str = Field(pattern="^(active|suspended|deactivated|locked)$")
    reason: Optional[str] = Field(default=None, max_length=500)


class DepartmentBrief(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class RoleBrief(BaseModel):
    id: uuid.UUID
    name: str
    display_name: Optional[str] = None

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: Optional[str] = None
    first_name: str
    last_name: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    status: str
    is_active: bool
    email_verified: bool = False
    mfa_enabled: bool = False
    avatar_url: Optional[str] = None
    job_title: Optional[str] = None
    employee_id: Optional[str] = None
    hire_date: Optional[datetime] = None
    last_login: Optional[datetime] = None
    department: Optional[DepartmentBrief] = None
    manager_id: Optional[uuid.UUID] = None
    roles: List[RoleBrief] = Field(default_factory=list)
    tenant_id: uuid.UUID
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    per_page: int
    pages: int


class UserSearchRequest(BaseModel):
    query: Optional[str] = None
    status: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    email_verified: Optional[bool] = None
    mfa_enabled: Optional[bool] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort_by: str = "created_at"
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")


class AccessEventBrief(BaseModel):
    id: uuid.UUID
    event_type: str
    resource_type: Optional[str] = None
    resource_id: Optional[uuid.UUID] = None
    resource_name: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserAccessHistoryResponse(BaseModel):
    user_id: uuid.UUID
    events: List[AccessEventBrief]
    total: int
    page: int
    per_page: int
    pages: int
