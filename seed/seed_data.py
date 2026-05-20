"""Seed script for demo data. Run: python -m seed.seed_data"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.tenant import Tenant
from backend.models.user import User
from backend.models.rbac import Role, Permission, RolePermission, UserRole, Department
from backend.models.application import Application, Entitlement, UserEntitlement
from backend.models.sod import SODPolicy, SODRule
from backend.utils.security import hash_password


async def seed(db: AsyncSession) -> None:
    print("Seeding demo data...")

    # Tenant
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="Acme Corporation",
        slug="acme",
        plan="enterprise",
        status="active",
        max_users=1000,
        features=["sod", "risk", "pam", "certifications", "workflow", "scim"],
    )
    db.add(tenant)

    # Departments
    dept_ids = {}
    for name in ["Engineering", "Finance", "HR", "Sales", "IT Operations", "Legal"]:
        d = Department(id=uuid.uuid4(), tenant_id=tenant_id, name=name, code=name[:3].upper())
        db.add(d)
        dept_ids[name] = d.id

    # Roles
    roles: dict[str, Role] = {}
    role_defs = [
        ("IGA Admin", "Full IGA platform administration", "system"),
        ("Manager", "Can approve access requests", "system"),
        ("Employee", "Standard employee access", "system"),
        ("IT Admin", "IT operations administrator", "custom"),
        ("Finance Analyst", "Finance application access", "custom"),
        ("HR Specialist", "HR system access", "custom"),
        ("Security Analyst", "Security monitoring access", "custom"),
        ("Developer", "Development environment access", "custom"),
    ]
    for name, desc, rtype in role_defs:
        r = Role(id=uuid.uuid4(), tenant_id=tenant_id, name=name, description=desc, role_type=rtype, is_active=True)
        db.add(r)
        roles[name] = r

    # Permissions
    perms_defs = [
        ("users:read", "Read user records", "users"),
        ("users:write", "Modify user records", "users"),
        ("users:delete", "Delete users", "users"),
        ("roles:read", "Read roles", "roles"),
        ("roles:write", "Modify roles", "roles"),
        ("access_requests:read", "Read access requests", "access_requests"),
        ("access_requests:write", "Submit access requests", "access_requests"),
        ("access_requests:approve", "Approve access requests", "access_requests"),
        ("certifications:read", "View certifications", "certifications"),
        ("certifications:manage", "Manage certifications", "certifications"),
        ("audit:read", "Read audit logs", "audit"),
        ("sod:read", "View SoD violations", "sod"),
        ("sod:manage", "Manage SoD policies", "sod"),
        ("risk:read", "View risk scores", "risk"),
        ("pam:read", "View PAM sessions", "pam"),
        ("pam:manage", "Manage privileged access", "pam"),
    ]
    perms: dict[str, Permission] = {}
    for name, desc, resource in perms_defs:
        p = Permission(id=uuid.uuid4(), tenant_id=tenant_id, name=name, description=desc, resource=resource, action=name.split(":")[1])
        db.add(p)
        perms[name] = p

    # Role-Permission assignments
    admin_perms = list(perms.values())
    for p in admin_perms:
        db.add(RolePermission(id=uuid.uuid4(), role_id=roles["IGA Admin"].id, permission_id=p.id))

    manager_perms = ["access_requests:approve", "users:read", "certifications:read", "certifications:manage"]
    for pname in manager_perms:
        if pname in perms:
            db.add(RolePermission(id=uuid.uuid4(), role_id=roles["Manager"].id, permission_id=perms[pname].id))

    employee_perms = ["access_requests:read", "access_requests:write"]
    for pname in employee_perms:
        if pname in perms:
            db.add(RolePermission(id=uuid.uuid4(), role_id=roles["Employee"].id, permission_id=perms[pname].id))

    # Users
    users_data = [
        ("admin@acme.com", "IGA", "Administrator", "IGA Admin", "IT Operations", True),
        ("alice.johnson@acme.com", "Alice", "Johnson", "Manager", "Engineering", False),
        ("bob.smith@acme.com", "Bob", "Smith", "Employee", "Engineering", False),
        ("carol.white@acme.com", "Carol", "White", "Employee", "Finance", False),
        ("david.brown@acme.com", "David", "Brown", "Manager", "Finance", False),
        ("eve.davis@acme.com", "Eve", "Davis", "Employee", "HR", False),
        ("frank.miller@acme.com", "Frank", "Miller", "IT Admin", "IT Operations", False),
        ("grace.wilson@acme.com", "Grace", "Wilson", "Security Analyst", "IT Operations", False),
    ]
    created_users: list[User] = []
    for email, fname, lname, role_name, dept_name, is_admin in users_data:
        u = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email=email,
            username=email.split("@")[0],
            first_name=fname,
            last_name=lname,
            full_name=f"{fname} {lname}",
            hashed_password=hash_password("Demo@123456"),
            is_active=True,
            is_superuser=is_admin,
            email_verified=True,
            department_id=dept_ids.get(dept_name),
        )
        db.add(u)
        created_users.append(u)
        if role_name in roles:
            db.add(UserRole(id=uuid.uuid4(), user_id=u.id, role_id=roles[role_name].id, tenant_id=tenant_id))
        db.add(UserRole(id=uuid.uuid4(), user_id=u.id, role_id=roles["Employee"].id, tenant_id=tenant_id))

    # Applications
    app_defs = [
        ("Salesforce CRM", "Customer relationship management", "saas"),
        ("Workday HR", "Human resources management", "saas"),
        ("GitHub Enterprise", "Source code management", "saas"),
        ("AWS Console", "Cloud infrastructure", "saas"),
        ("ServiceNow", "IT service management", "saas"),
        ("Oracle ERP", "Enterprise resource planning", "on_premise"),
    ]
    apps: list[Application] = []
    for name, desc, atype in app_defs:
        a = Application(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            description=desc,
            application_type=atype,
            status="active",
            owner_id=created_users[0].id,
        )
        db.add(a)
        apps.append(a)

    # Entitlements
    entitlement_defs = [
        (0, "CRM User", "Standard CRM access", "low"),
        (0, "CRM Admin", "Full CRM administration", "high"),
        (0, "CRM Reports", "CRM reporting access", "low"),
        (1, "HR Employee", "Employee self-service", "low"),
        (1, "HR Manager", "Manager HR access", "medium"),
        (1, "HR Admin", "Full HR administration", "high"),
        (1, "Payroll Admin", "Payroll processing access", "critical"),
        (2, "Developer", "Code read access", "low"),
        (2, "Maintainer", "Code write access", "medium"),
        (2, "Admin", "Repository administration", "high"),
        (3, "Developer", "Dev environment access", "medium"),
        (3, "Admin", "Full AWS administration", "critical"),
        (4, "Requester", "Submit tickets", "low"),
        (4, "IT Admin", "Manage all tickets", "medium"),
        (5, "AP Clerk", "Accounts payable", "high"),
        (5, "GL Accountant", "General ledger access", "high"),
        (5, "CFO Access", "Full financial access", "critical"),
    ]
    entitlements: list[Entitlement] = []
    for app_idx, name, desc, risk in entitlement_defs:
        e = Entitlement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            application_id=apps[app_idx].id,
            name=name,
            description=desc,
            risk_level=risk,
            is_requestable=True,
        )
        db.add(e)
        entitlements.append(e)

    # Assign some entitlements to users
    assignments = [
        (1, 0),  # Alice -> CRM User
        (1, 3),  # Alice -> HR Employee
        (2, 0),  # Bob -> CRM User
        (2, 7),  # Bob -> GitHub Developer
        (3, 13), # Carol -> AP Clerk
        (3, 14), # Carol -> GL Accountant
        (4, 14), # David -> GL Accountant
        (4, 6),  # David -> Payroll Admin (SoD violation with AP Clerk setup)
    ]
    for user_idx, ent_idx in assignments:
        db.add(UserEntitlement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=created_users[user_idx].id,
            entitlement_id=entitlements[ent_idx].id,
            is_active=True,
            granted_at=datetime.now(timezone.utc),
            granted_by_id=created_users[0].id,
        ))

    # SoD Policy
    sod_policy = SODPolicy(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Financial Controls SoD",
        description="Prevents conflicts of interest in financial processing",
        is_active=True,
    )
    db.add(sod_policy)
    db.add(SODRule(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        policy_id=sod_policy.id,
        name="AP Clerk + Payroll Admin",
        description="Accounts Payable and Payroll should be separate",
        severity="critical",
        entitlement_ids=[str(entitlements[13].id), str(entitlements[6].id)],
        is_active=True,
    ))

    await db.commit()
    print(f"✓ Seed complete: tenant={tenant.slug}, {len(created_users)} users, {len(apps)} apps, {len(entitlements)} entitlements")


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
