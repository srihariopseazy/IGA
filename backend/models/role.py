# Compatibility shim — imports are expected from backend.models.role in some routes.
from backend.models.rbac import Role, Permission, RolePermission, UserRole, Department

__all__ = ["Role", "Permission", "RolePermission", "UserRole", "Department"]
