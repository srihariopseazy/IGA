from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging


@dataclass
class ConnectorResult:
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class UserAccount:
    external_id: str
    username: str
    email: str
    first_name: str
    last_name: str
    is_active: bool
    groups: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Base class for all IGA connectors."""

    connector_type: str = "base"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f"connector.{self.connector_type}")

    @abstractmethod
    async def test_connection(self) -> ConnectorResult:
        """Test connectivity to the target system."""
        ...

    @abstractmethod
    async def create_user(self, user: UserAccount) -> ConnectorResult:
        """Create a user account in the target system."""
        ...

    @abstractmethod
    async def update_user(self, external_id: str, attributes: Dict[str, Any]) -> ConnectorResult:
        """Update a user account."""
        ...

    @abstractmethod
    async def delete_user(self, external_id: str) -> ConnectorResult:
        """Delete/deactivate a user account."""
        ...

    @abstractmethod
    async def enable_user(self, external_id: str) -> ConnectorResult:
        """Enable a disabled user account."""
        ...

    @abstractmethod
    async def disable_user(self, external_id: str) -> ConnectorResult:
        """Disable a user account."""
        ...

    @abstractmethod
    async def get_user(self, external_id: str) -> ConnectorResult:
        """Get user details from target system."""
        ...

    @abstractmethod
    async def list_users(self, filter: str = None) -> ConnectorResult:
        """List users from target system."""
        ...

    async def add_to_group(self, user_id: str, group_id: str) -> ConnectorResult:
        """Add user to a group (optional)."""
        return ConnectorResult(success=False, error="Not supported")

    async def remove_from_group(self, user_id: str, group_id: str) -> ConnectorResult:
        """Remove user from a group (optional)."""
        return ConnectorResult(success=False, error="Not supported")

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        """Reset user password (optional)."""
        return ConnectorResult(success=False, error="Not supported")

    async def get_health(self) -> Dict[str, Any]:
        """Return connector health status."""
        try:
            result = await self.test_connection()
            return {
                "status": "healthy" if result.success else "unhealthy",
                "connector_type": self.connector_type,
                "timestamp": datetime.utcnow().isoformat(),
                "error": result.error,
            }
        except Exception as e:
            return {
                "status": "error",
                "connector_type": self.connector_type,
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }

    def _decrypt_config(self, key: str) -> str:
        """Decrypt sensitive config value."""
        from backend.utils.security import decrypt_field
        import base64
        from backend.config import settings

        encrypted = self.config.get(key, "")
        if encrypted and encrypted.startswith("enc:"):
            return decrypt_field(encrypted[4:], base64.b64decode(settings.ENCRYPTION_KEY))
        return encrypted or ""
