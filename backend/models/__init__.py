# Import all models so that Alembic (and SQLAlchemy) can detect every table.
# The import order matters only where FK references exist across modules; we
# therefore import lower-level (no-FK) models first and higher-level ones after.

# Core base (must come first so Base.metadata is populated)
from backend.database import Base  # noqa: F401

# ── Tenancy ──────────────────────────────────────────────────────────────────
from backend.models.tenant import (  # noqa: F401
    Tenant,
    TenantBranding,
    TenantUsageMetering,
)

# ── Connectors (referenced by Application, Sync) ─────────────────────────────
from backend.models.connector import (  # noqa: F401
    Connector,
    ConnectorConfig,
)

# ── RBAC (Role/Dept referenced by User) ──────────────────────────────────────
from backend.models.rbac import (  # noqa: F401
    Department,
    Role,
    Permission,
    RolePermission,
    UserRole,
    DynamicRoleRule,
)

# ── Users ─────────────────────────────────────────────────────────────────────
from backend.models.user import (  # noqa: F401
    User,
    UserProfile,
    LoginHistory,
    Session,
    MFADevice,
    PasswordResetToken,
    EmailVerificationToken,
    OTPCode,
)

# ── Applications & Entitlements ───────────────────────────────────────────────
from backend.models.application import (  # noqa: F401
    Application,
    Entitlement,
    UserEntitlement,
)

# ── Workflows (referenced by AccessRequest) ───────────────────────────────────
from backend.models.workflow import (  # noqa: F401
    ApprovalWorkflow,
    WorkflowStep,
    WorkflowInstance,
    WorkflowStepInstance,
)

# ── Access Requests ───────────────────────────────────────────────────────────
from backend.models.access_request import (  # noqa: F401
    AccessRequest,
    AccessRequestItem,
    Approval,
)

# ── Provisioning ─────────────────────────────────────────────────────────────
from backend.models.provisioning import (  # noqa: F401
    ProvisioningTask,
    ProvisioningLog,
)

# ── Certification ─────────────────────────────────────────────────────────────
from backend.models.certification import (  # noqa: F401
    CertificationCampaign,
    CertificationItem,
    CertificationReviewer,
)

# ── Separation of Duties ──────────────────────────────────────────────────────
from backend.models.sod import (  # noqa: F401
    SODPolicy,
    SODRule,
    SODViolation,
)

# ── Risk & Analytics ──────────────────────────────────────────────────────────
from backend.models.risk import (  # noqa: F401
    RiskScore,
    IdentityRiskHistory,
    UserBehaviorEvent,
    AccessRecommendation,
)

# ── Audit & Compliance ────────────────────────────────────────────────────────
from backend.models.audit import (  # noqa: F401
    AuditLog,
    ComplianceReport,
)

# ── Privileged Access Management ─────────────────────────────────────────────
from backend.models.pam import (  # noqa: F401
    PrivilegedAccount,
    PAMSession,
    BreakGlassRequest,
)

# ── OAuth / OIDC ──────────────────────────────────────────────────────────────
from backend.models.oauth import (  # noqa: F401
    OAuthClient,
    OAuthToken,
)

# ── Notifications ─────────────────────────────────────────────────────────────
from backend.models.notification import (  # noqa: F401
    Notification,
    NotificationTemplate,
)

# ── Directory Sync ────────────────────────────────────────────────────────────
from backend.models.sync import (  # noqa: F401
    HRMSSyncJob,
    LDAPSyncJob,
    SCIMSyncJob,
)

# ── Contractors & Temporary Access ────────────────────────────────────────────
from backend.models.contractor import (  # noqa: F401
    ContractorProfile,
    TemporaryAccessGrant,
)

# ── Policy & Device Trust ─────────────────────────────────────────────────────
from backend.models.policy import (  # noqa: F401
    PolicyRule,
    GeoRestriction,
    DeviceTrustRecord,
)

__all__ = [
    # Base
    "Base",
    # Tenant
    "Tenant",
    "TenantBranding",
    "TenantUsageMetering",
    # Connector
    "Connector",
    "ConnectorConfig",
    # RBAC
    "Department",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "DynamicRoleRule",
    # User
    "User",
    "UserProfile",
    "LoginHistory",
    "Session",
    "MFADevice",
    "PasswordResetToken",
    "EmailVerificationToken",
    "OTPCode",
    # Application
    "Application",
    "Entitlement",
    "UserEntitlement",
    # Workflow
    "ApprovalWorkflow",
    "WorkflowStep",
    "WorkflowInstance",
    "WorkflowStepInstance",
    # Access Request
    "AccessRequest",
    "AccessRequestItem",
    "Approval",
    # Provisioning
    "ProvisioningTask",
    "ProvisioningLog",
    # Certification
    "CertificationCampaign",
    "CertificationItem",
    "CertificationReviewer",
    # SoD
    "SODPolicy",
    "SODRule",
    "SODViolation",
    # Risk
    "RiskScore",
    "IdentityRiskHistory",
    "UserBehaviorEvent",
    "AccessRecommendation",
    # Audit
    "AuditLog",
    "ComplianceReport",
    # PAM
    "PrivilegedAccount",
    "PAMSession",
    "BreakGlassRequest",
    # OAuth
    "OAuthClient",
    "OAuthToken",
    # Notification
    "Notification",
    "NotificationTemplate",
    # Sync
    "HRMSSyncJob",
    "LDAPSyncJob",
    "SCIMSyncJob",
    # Contractor
    "ContractorProfile",
    "TemporaryAccessGrant",
    # Policy
    "PolicyRule",
    "GeoRestriction",
    "DeviceTrustRecord",
]
