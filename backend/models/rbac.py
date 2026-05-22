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



class Role(Base):
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_requestable = Column(Boolean, nullable=False, default=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    parent_role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True)
    risk_level = Column(String(50), nullable=True, default="low", index=True)
    role_metadata = Column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    parent = relationship("Role", primaryjoin="Role.parent_role_id==Role.id", back_populates="children", foreign_keys="[Role.parent_role_id]", remote_side="Role.id")
    children = relationship("Role", primaryjoin="Role.id==Role.parent_role_id", back_populates="parent", foreign_keys="[Role.parent_role_id]")
    permissions = relationship(
        "RolePermission", back_populates="role", lazy="select"
    )
    dynamic_rules = relationship(
        "DynamicRoleRule", back_populates="role", lazy="select"
    )

    __table_args__ = (
        Index("ix_roles_tenant_name", "tenant_id", "name"),
            )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r} type={self.type}>"


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
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
        Index("ix_permissions_tenant_resource_action", "tenant_id", "resource", "action"),
    )

    def __repr__(self) -> str:
        return f"<Permission id={self.id} resource={self.resource!r} action={self.action!r}>"


class RolePermission(Base):
    __tablename__ = "role_permission"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id = Column(
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
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
    __tablename__ = "user_role_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
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
        Index("ix_user_role_assignments_user_role", "user_id", "role_id"),
        Index("ix_user_role_assignments_tenant_user", "tenant_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<UserRole user_id={self.user_id} role_id={self.role_id}>"


class DynamicRoleRule(Base):
    __tablename__ = "dynamic_role_rule"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
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
