# Compatibility shim — imports are expected from backend.models.entitlement in some routes.
from backend.models.application import Entitlement, UserEntitlement

__all__ = ["Entitlement", "UserEntitlement"]
