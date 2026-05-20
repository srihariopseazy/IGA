from __future__ import annotations

import uuid
from typing import Optional

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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class Connector(Base):
    __tablename__ = "connector"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    connector_type = Column(
        SAEnum(
            "ldap",
            "scim",
            "rest",
            "ssh",
            "database",
            "m365",
            "google_workspace",
            "salesforce",
            "servicenow",
            "jira",
            "slack",
            "teams",
            "sap",
            "custom",
            name="connector_type_enum",
        ),
        nullable=False,
        index=True,
    )
    status = Column(
        SAEnum("active", "inactive", "error", name="connector_status_enum"),
        nullable=False,
        default="inactive",
        index=True,
    )
    health_status = Column(String(50), nullable=True)
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    configs = relationship("ConnectorConfig", back_populates="connector", lazy="select")

    __table_args__ = (
        Index("ix_connector_tenant_type", "tenant_id", "connector_type"),
        Index("ix_connector_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Connector id={self.id} name={self.name!r} "
            f"type={self.connector_type} status={self.status}>"
        )


class ConnectorConfig(Base):
    __tablename__ = "connector_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    connector_id = Column(
        UUID(as_uuid=True),
        ForeignKey("connector.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_key = Column(String(255), nullable=False)
    config_value_encrypted = Column(Text, nullable=True)
    is_sensitive = Column(Boolean, nullable=False, default=False)

    # Relationships
    connector = relationship("Connector", back_populates="configs")

    __table_args__ = (
        Index(
            "ix_connector_config_connector_key",
            "connector_id",
            "config_key",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConnectorConfig id={self.id} connector_id={self.connector_id} "
            f"config_key={self.config_key!r}>"
        )
