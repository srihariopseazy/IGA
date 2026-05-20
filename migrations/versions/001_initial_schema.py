"""Initial schema — all IGA platform tables.

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000

This migration creates the complete database schema for the IGA platform:
  - Multi-tenant core (tenants)
  - Identity & Users (users, user_profiles, external_identities)
  - Access (roles, permissions, entitlements, role_assignments)
  - Applications (applications, app_accounts, app_entitlements)
  - Access Requests (access_requests, request_items, approvals)
  - Certification Campaigns (campaigns, campaign_items, certifiers)
  - Segregation of Duties (sod_rules, sod_violations)
  - Provisioning (provisioning_tasks, provisioning_logs)
  - Workflows (workflow_definitions, workflow_instances, workflow_tasks)
  - Risk (risk_scores, risk_factors, risk_events)
  - Audit (audit_logs)
  - Notifications (notifications, notification_templates)
  - Webhooks (webhooks, webhook_deliveries)
  - LDAP (ldap_configurations, ldap_sync_jobs)
  - Sessions (user_sessions, mfa_tokens)
  - Settings (tenant_settings, system_settings)
  - Delegation (access_delegations)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from alembic import op

# ─── Revision identifiers ────────────────────────────────────────────────────
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # EXTENSIONS
    # =========================================================================
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gin"')

    # =========================================================================
    # TENANTS
    # =========================================================================
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("domain", sa.String(253), nullable=True),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_trial", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("trial_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_users", sa.Integer, nullable=True),
        sa.Column("plan_tier", sa.String(50), nullable=False, server_default=sa.text("'standard'")),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_domain", "tenants", ["domain"], postgresql_where=sa.text("domain IS NOT NULL"))
    op.create_index("ix_tenants_active", "tenants", ["is_active"], postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # USERS
    # =========================================================================
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("password_hash", sa.Text, nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default=sa.text("'en'")),
        sa.Column("timezone", sa.String(64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_service_account", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_external", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_reason", sa.Text, nullable=True),
        sa.Column("mfa_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("mfa_secret", sa.Text, nullable=True),
        sa.Column("mfa_backup_codes", JSONB, nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_ip", INET, nullable=True),
        sa.Column("failed_login_attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employee_id", sa.String(100), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column("manager_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("hire_date", sa.Date, nullable=True),
        sa.Column("termination_date", sa.Date, nullable=True),
        sa.Column("cost_center", sa.String(100), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default=sa.text("'local'")),
        sa.Column("risk_score", sa.Float, nullable=False, server_default=sa.text("0.0")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_tenant_email", "users", ["tenant_id", "email"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_users_tenant_username", "users", ["tenant_id", "username"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_users_tenant_active", "users", ["tenant_id", "is_active"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_users_manager", "users", ["manager_id"], postgresql_where=sa.text("manager_id IS NOT NULL"))
    op.create_index("ix_users_employee_id", "users", ["tenant_id", "employee_id"],
                    postgresql_where=sa.text("employee_id IS NOT NULL AND deleted_at IS NULL"))
    op.create_index("ix_users_email_trgm", "users", ["email"], postgresql_ops={"email": "gin_trgm_ops"},
                    postgresql_using="gin")

    # =========================================================================
    # USER PROFILES (extended attributes)
    # =========================================================================
    op.create_table(
        "user_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("linkedin_url", sa.Text, nullable=True),
        sa.Column("custom_attributes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notification_preferences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ui_preferences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])

    # =========================================================================
    # EXTERNAL IDENTITIES (SSO / federated)
    # =========================================================================
    op.create_table(
        "external_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_user_id", sa.String(512), nullable=False),
        sa.Column("provider_data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])
    op.create_index("ix_external_identities_provider", "external_identities", ["provider", "provider_user_id"], unique=True)

    # =========================================================================
    # APPLICATIONS
    # =========================================================================
    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(50), nullable=False, server_default=sa.text("'web'")),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_privileged", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("connector_type", sa.String(100), nullable=True),
        sa.Column("connector_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provisioning_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_applications_tenant_id", "applications", ["tenant_id"])
    op.create_index("ix_applications_tenant_slug", "applications", ["tenant_id", "slug"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # APP ENTITLEMENTS (roles/groups/permissions within an application)
    # =========================================================================
    op.create_table(
        "app_entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(50), nullable=False, server_default=sa.text("'role'")),
        sa.Column("is_privileged", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("requires_justification", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("max_grant_duration_days", sa.Integer, nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default=sa.text("'low'")),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_entitlements_tenant_id", "app_entitlements", ["tenant_id"])
    op.create_index("ix_app_entitlements_application_id", "app_entitlements", ["application_id"])
    op.create_index("ix_app_entitlements_tenant_app", "app_entitlements", ["tenant_id", "application_id"],
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # APP ACCOUNTS (user accounts within an application)
    # =========================================================================
    op.create_table(
        "app_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(512), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_privileged", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_orphaned", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_accounts_tenant_id", "app_accounts", ["tenant_id"])
    op.create_index("ix_app_accounts_user_id", "app_accounts", ["user_id"])
    op.create_index("ix_app_accounts_tenant_user_app", "app_accounts", ["tenant_id", "user_id", "application_id"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_app_accounts_orphaned", "app_accounts", ["tenant_id", "is_orphaned"],
                    postgresql_where=sa.text("is_orphaned = true AND deleted_at IS NULL"))

    # =========================================================================
    # APP ACCOUNT ENTITLEMENTS (grants of entitlements to app accounts)
    # =========================================================================
    op.create_table(
        "app_account_entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_account_id", UUID(as_uuid=True), sa.ForeignKey("app_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_id", UUID(as_uuid=True), sa.ForeignKey("app_entitlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("grant_reason", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_app_acct_entitlements_tenant", "app_account_entitlements", ["tenant_id"])
    op.create_index("ix_app_acct_entitlements_account", "app_account_entitlements", ["app_account_id"])
    op.create_index("ix_app_acct_entitlements_entitlement", "app_account_entitlements", ["entitlement_id"])
    op.create_index("ix_app_acct_entitlements_active", "app_account_entitlements", ["tenant_id", "is_active"],
                    postgresql_where=sa.text("is_active = true"))

    # =========================================================================
    # ROLES (IGA business roles)
    # =========================================================================
    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(50), nullable=False, server_default=sa.text("'business'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_requestable", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parent_role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default=sa.text("'low'")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])
    op.create_index("ix_roles_tenant_slug", "roles", ["tenant_id", "slug"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # ROLE ENTITLEMENT MAPPINGS
    # =========================================================================
    op.create_table(
        "role_entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_id", UUID(as_uuid=True), sa.ForeignKey("app_entitlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_role_entitlements_role", "role_entitlements", ["role_id"])
    op.create_index("ix_role_entitlements_entitlement", "role_entitlements", ["entitlement_id"])
    op.create_index("ix_role_entitlements_unique", "role_entitlements", ["role_id", "entitlement_id"], unique=True)

    # =========================================================================
    # USER ROLE ASSIGNMENTS
    # =========================================================================
    op.create_table(
        "user_role_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(50), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_role_assignments_tenant", "user_role_assignments", ["tenant_id"])
    op.create_index("ix_user_role_assignments_user", "user_role_assignments", ["user_id"])
    op.create_index("ix_user_role_assignments_role", "user_role_assignments", ["role_id"])
    op.create_index("ix_user_role_unique_active", "user_role_assignments", ["user_id", "role_id"],
                    unique=True, postgresql_where=sa.text("is_active = true"))

    # =========================================================================
    # ACCESS REQUESTS
    # =========================================================================
    op.create_table(
        "access_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_number", sa.String(20), nullable=False),
        sa.Column("requester_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("request_type", sa.String(30), nullable=False, server_default=sa.text("'grant'")),
        sa.Column("priority", sa.String(20), nullable=False, server_default=sa.text("'normal'")),
        sa.Column("justification", sa.Text, nullable=True),
        sa.Column("business_justification", sa.Text, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column("sod_violations", JSONB, nullable=True),
        sa.Column("workflow_instance_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_access_requests_tenant_id", "access_requests", ["tenant_id"])
    op.create_index("ix_access_requests_requester", "access_requests", ["requester_id"])
    op.create_index("ix_access_requests_target_user", "access_requests", ["target_user_id"])
    op.create_index("ix_access_requests_tenant_status", "access_requests", ["tenant_id", "status"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_access_requests_number", "access_requests", ["tenant_id", "request_number"], unique=True)

    # =========================================================================
    # ACCESS REQUEST ITEMS
    # =========================================================================
    op.create_table(
        "access_request_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(30), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entitlement_id", UUID(as_uuid=True), sa.ForeignKey("app_entitlements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provisioning_task_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_request_items_request_id", "access_request_items", ["request_id"])
    op.create_index("ix_request_items_status", "access_request_items", ["status"])

    # =========================================================================
    # APPROVALS
    # =========================================================================
    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approver_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("comments", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_to_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_approvals_tenant_id", "approvals", ["tenant_id"])
    op.create_index("ix_approvals_request_id", "approvals", ["request_id"])
    op.create_index("ix_approvals_approver_id", "approvals", ["approver_id"])
    op.create_index("ix_approvals_approver_pending", "approvals", ["approver_id", "status"],
                    postgresql_where=sa.text("status = 'pending'"))

    # =========================================================================
    # SOD RULES
    # =========================================================================
    op.create_table(
        "sod_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default=sa.text("'high'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_hard_block", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("conflicting_items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mitigation_control", sa.Text, nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sod_rules_tenant_id", "sod_rules", ["tenant_id"])
    op.create_index("ix_sod_rules_active", "sod_rules", ["tenant_id", "is_active"],
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # SOD VIOLATIONS
    # =========================================================================
    op.create_table(
        "sod_violations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", UUID(as_uuid=True), sa.ForeignKey("sod_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mitigated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mitigation_notes", sa.Text, nullable=True),
        sa.Column("exception_approved_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("access_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conflict_details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sod_violations_tenant_id", "sod_violations", ["tenant_id"])
    op.create_index("ix_sod_violations_user_id", "sod_violations", ["user_id"])
    op.create_index("ix_sod_violations_rule_id", "sod_violations", ["rule_id"])
    op.create_index("ix_sod_violations_open", "sod_violations", ["tenant_id", "status"],
                    postgresql_where=sa.text("status = 'open'"))

    # =========================================================================
    # CERTIFICATION CAMPAIGNS
    # =========================================================================
    op.create_table(
        "certification_campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(50), nullable=False, server_default=sa.text("'user_access'")),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scope", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_revoke_on_expiry", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("total_items", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("certified_items", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("revoked_items", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cert_campaigns_tenant_id", "certification_campaigns", ["tenant_id"])
    op.create_index("ix_cert_campaigns_status", "certification_campaigns", ["tenant_id", "status"],
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # CERTIFICATION ITEMS
    # =========================================================================
    op.create_table(
        "certification_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("certification_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("certifier_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(30), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entitlement_id", UUID(as_uuid=True), sa.ForeignKey("app_entitlements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comments", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_cert_items_campaign_id", "certification_items", ["campaign_id"])
    op.create_index("ix_cert_items_certifier_id", "certification_items", ["certifier_id"])
    op.create_index("ix_cert_items_subject_user", "certification_items", ["subject_user_id"])
    op.create_index("ix_cert_items_pending", "certification_items", ["campaign_id", "certifier_id"],
                    postgresql_where=sa.text("status = 'pending'"))

    # =========================================================================
    # PROVISIONING TASKS
    # =========================================================================
    op.create_table(
        "provisioning_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("5")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entitlement_id", UUID(as_uuid=True), sa.ForeignKey("app_entitlements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("access_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_provisioning_tasks_tenant_id", "provisioning_tasks", ["tenant_id"])
    op.create_index("ix_provisioning_tasks_user_id", "provisioning_tasks", ["user_id"])
    op.create_index("ix_provisioning_tasks_pending", "provisioning_tasks", ["tenant_id", "status", "priority"],
                    postgresql_where=sa.text("status IN ('pending', 'retrying')"))
    op.create_index("ix_provisioning_tasks_celery", "provisioning_tasks", ["celery_task_id"],
                    postgresql_where=sa.text("celery_task_id IS NOT NULL"))

    # =========================================================================
    # PROVISIONING LOGS
    # =========================================================================
    op.create_table(
        "provisioning_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("provisioning_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(10), nullable=False, server_default=sa.text("'INFO'")),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_provisioning_logs_task_id", "provisioning_logs", ["task_id"])
    op.create_index("ix_provisioning_logs_created_at", "provisioning_logs", ["created_at"])

    # =========================================================================
    # RISK SCORES
    # =========================================================================
    op.create_table(
        "risk_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float, nullable=False, server_default=sa.text("0.0")),
        sa.Column("level", sa.String(20), nullable=False, server_default=sa.text("'low'")),
        sa.Column("factors", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_risk_scores_tenant_entity", "risk_scores", ["tenant_id", "entity_type", "entity_id"])
    op.create_index("ix_risk_scores_high", "risk_scores", ["tenant_id", "level"],
                    postgresql_where=sa.text("level IN ('high', 'critical')"))

    # =========================================================================
    # AUDIT LOGS
    # =========================================================================
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("resource_name", sa.String(500), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False, server_default=sa.text("'success'")),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("before_state", JSONB, nullable=True),
        sa.Column("after_state", JSONB, nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_tenant_action", "audit_logs", ["tenant_id", "action"])
    op.create_index("ix_audit_logs_tenant_resource", "audit_logs", ["tenant_id", "resource_type", "resource_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["tenant_id", "created_at"])

    # =========================================================================
    # USER SESSIONS
    # =========================================================================
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("refresh_token_hash", sa.String(64), nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("device_info", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("mfa_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["session_token_hash"])
    op.create_index("ix_user_sessions_active", "user_sessions", ["user_id", "is_active"],
                    postgresql_where=sa.text("is_active = true"))

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default=sa.text("'in_app'")),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
    op.create_index("ix_notifications_unread", "notifications", ["recipient_id", "is_read"],
                    postgresql_where=sa.text("is_read = false"))
    op.create_index("ix_notifications_tenant_created", "notifications", ["tenant_id", "created_at"])

    # =========================================================================
    # WEBHOOKS
    # =========================================================================
    op.create_table(
        "webhooks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("events", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("headers", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default=sa.text("30")),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhooks_tenant_id", "webhooks", ["tenant_id"])
    op.create_index("ix_webhooks_active", "webhooks", ["tenant_id", "is_active"],
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # WEBHOOK DELIVERIES
    # =========================================================================
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("webhook_id", UUID(as_uuid=True), sa.ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("response_status_code", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_webhook_deliveries_webhook_id", "webhook_deliveries", ["webhook_id"])
    op.create_index("ix_webhook_deliveries_pending", "webhook_deliveries", ["status", "next_attempt_at"],
                    postgresql_where=sa.text("status IN ('pending', 'retrying')"))

    # =========================================================================
    # LDAP CONFIGURATIONS
    # =========================================================================
    op.create_table(
        "ldap_configurations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("server_url", sa.String(512), nullable=False),
        sa.Column("bind_dn", sa.String(512), nullable=False),
        sa.Column("bind_password_encrypted", sa.Text, nullable=False),
        sa.Column("base_dn", sa.String(512), nullable=False),
        sa.Column("user_search_base", sa.String(512), nullable=False),
        sa.Column("group_search_base", sa.String(512), nullable=False),
        sa.Column("attribute_mapping", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("sync_interval_minutes", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ldap_configs_tenant_id", "ldap_configurations", ["tenant_id"])

    # =========================================================================
    # LDAP SYNC JOBS
    # =========================================================================
    op.create_table(
        "ldap_sync_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("ldap_config_id", UUID(as_uuid=True), sa.ForeignKey("ldap_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("sync_type", sa.String(30), nullable=False, server_default=sa.text("'incremental'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("users_created", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("users_updated", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("users_deactivated", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ldap_sync_jobs_config_id", "ldap_sync_jobs", ["ldap_config_id"])

    # =========================================================================
    # WORKFLOW DEFINITIONS
    # =========================================================================
    op.create_table(
        "workflow_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("trigger_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("steps", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_definitions_tenant_id", "workflow_definitions", ["tenant_id"])
    op.create_index("ix_workflow_definitions_tenant_slug", "workflow_definitions", ["tenant_id", "slug"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # =========================================================================
    # WORKFLOW INSTANCES
    # =========================================================================
    op.create_table(
        "workflow_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("definition_id", UUID(as_uuid=True), sa.ForeignKey("workflow_definitions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'running'")),
        sa.Column("current_step", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("context", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflow_instances_tenant_id", "workflow_instances", ["tenant_id"])
    op.create_index("ix_workflow_instances_running", "workflow_instances", ["tenant_id", "status"],
                    postgresql_where=sa.text("status = 'running'"))

    # =========================================================================
    # ACCESS DELEGATIONS
    # =========================================================================
    op.create_table(
        "access_delegations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delegator_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delegate_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_access_delegations_tenant_id", "access_delegations", ["tenant_id"])
    op.create_index("ix_access_delegations_delegator", "access_delegations", ["delegator_id"])
    op.create_index("ix_access_delegations_delegate", "access_delegations", ["delegate_id"])
    op.create_index("ix_access_delegations_active", "access_delegations", ["tenant_id", "is_active", "expires_at"],
                    postgresql_where=sa.text("is_active = true"))

    # =========================================================================
    # TENANT SETTINGS
    # =========================================================================
    op.create_table(
        "tenant_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("password_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("mfa_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("session_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provisioning_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("certification_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notification_settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("branding", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("feature_flags", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tenant_settings_tenant_id", "tenant_settings", ["tenant_id"])

    # =========================================================================
    # updated_at auto-update trigger function
    # =========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    tables_with_updated_at = [
        "tenants", "users", "applications", "app_entitlements", "app_accounts",
        "app_account_entitlements", "roles", "user_role_assignments",
        "access_requests", "access_request_items", "approvals", "sod_rules",
        "sod_violations", "certification_campaigns", "certification_items",
        "provisioning_tasks", "risk_scores", "user_sessions", "webhooks",
        "webhook_deliveries", "ldap_configurations", "workflow_definitions",
        "workflow_instances", "access_delegations", "tenant_settings",
    ]
    for table in tables_with_updated_at:
        op.execute(f"""
            CREATE TRIGGER trigger_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    tables = [
        "tenant_settings", "access_delegations", "workflow_instances",
        "workflow_definitions", "ldap_sync_jobs", "ldap_configurations",
        "webhook_deliveries", "webhooks", "notifications", "user_sessions",
        "audit_logs", "risk_scores", "provisioning_logs", "provisioning_tasks",
        "certification_items", "certification_campaigns", "sod_violations",
        "sod_rules", "approvals", "access_request_items", "access_requests",
        "user_role_assignments", "role_entitlements", "roles",
        "app_account_entitlements", "app_accounts", "app_entitlements",
        "applications", "external_identities", "user_profiles", "users",
        "tenants",
    ]
    for table in tables:
        op.drop_table(table)

    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;")
    op.execute('DROP EXTENSION IF EXISTS "btree_gin";')
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm";')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto";')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp";')
