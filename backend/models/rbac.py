from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class Department(Base):
    __tablename__ = "department"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    code = Column(String(100), nullable=True)
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    manager_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    description = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    parent = relationship("Department", remote_side="Department.id", foreign_keys=[parent_id])
    children = relationship("Department", back_populates="parent", foreign_keys=[parent_id])

    __table_args__ = (
        Index("ix_department_tenant_code", "tenant_id", "code"),
        Index("ix_department_tenant_name", "tenant_id", "name"),
    )

    def __repr__(self) -> str:
        return f"<Department id={self.id} name={self.name!r}>"


class Role(Base):
    __tablename__ = "role"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    role_type = Column(
        SAEnum("business", "technical", "dynamic", name="role_type_enum"),
        nullable=False,
        default="business",
        index=True,
    )
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_privileged = Column(Boolean, nullable=False, default=False)
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="role_risk_level_enum"),
        nullable=False,
        default="low",
        index=True,
    )
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    parent = relationship("Role", remote_side="Role.id", foreign_keys=[parent_id])
    children = relationship("Role", back_populates="parent", foreign_keys=[parent_id])
    permissions = relationship(
        "RolePermission", back_populates="role", lazy="select"
    )
    dynamic_rules = relationship(
        "DynamicRoleRule", back_populates="role", lazy="select"
    )

    __table_args__ = (
        Index("ix_role_tenant_name", "tenant_id", "name"),
        Index("ix_role_tenant_type", "tenant_id", "role_type"),
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r} type={self.role_type}>"


class Permission(Base):
    __tablename__ = "permission"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    resource = Column(String(255), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    conditions = Column(JSONB, nullable=True, default=dict)
    description = Column(Text, nullable=True)

    # Relationships
    role_permissions = relationship("RolePermission", back_populates="permission", lazy="select")

    __table_args__ = (
        Index("ix_permission_tenant_resource_action", "tenant_id", "resource", "action"),
    )

    def __repr__(self) -> str:
        return f"<Permission id={self.id} resource={self.resource!r} action={self.action!r}>"


class RolePermission(Base):
    __tablename__ = "role_permission"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id = Column(
        UUID(as_uuid=True),
        ForeignKey("permission.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission", back_populates="role_permissions")

    __table_args__ = (
        Index("ix_role_permission_role_permission", "role_id", "permission_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<RolePermission role_id={self.role_id} permission_id={self.permission_id}>"


class UserRole(Base):
    __tablename__ = "user_role"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by = Column(UUID(as_uuid=True), nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    justification = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    role = relationship("Role", foreign_keys=[role_id])

    __table_args__ = (
        Index("ix_user_role_user_role", "user_id", "role_id"),
        Index("ix_user_role_tenant_user", "tenant_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<UserRole user_id={self.user_id} role_id={self.role_id}>"


class DynamicRoleRule(Base):
    __tablename__ = "dynamic_role_rule"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attribute_key = Column(String(255), nullable=False)
    operator = Column(String(50), nullable=False)
    attribute_value = Column(String(255), nullable=False)

    # Relationships
    role = relationship("Role", back_populates="dynamic_rules")

    __table_args__ = (
        Index("ix_dynamic_role_rule_role", "role_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<DynamicRoleRule id={self.id} role_id={self.role_id} "
            f"attribute_key={self.attribute_key!r}>"
        )
