from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.pam import BreakGlassRequest, PAMSession, PrivilegedAccount
from backend.models.user import User
from backend.audit.audit_logger import audit_logger

router = APIRouter(prefix="/pam", tags=["Privileged Access Management"])

# Default session duration: 4 hours
DEFAULT_SESSION_HOURS = 4
DEFAULT_BREAK_GLASS_HOURS = 1


class PrivilegedAccountCreate(BaseModel):
    account_name: str
    account_type: str  # admin, root, service, shared
    system_name: str
    owner_id: Optional[UUID] = None
    risk_level: str = "high"
    is_vaulted: bool = False


class PrivilegedAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    system_name: Optional[str] = None
    owner_id: Optional[UUID] = None
    risk_level: Optional[str] = None
    is_vaulted: Optional[bool] = None


class SessionRequest(BaseModel):
    privileged_account_id: UUID
    justification: str
    session_type: str = "interactive"
    duration_hours: int = DEFAULT_SESSION_HOURS


class BreakGlassCreate(BaseModel):
    privileged_account_id: UUID
    justification: str
    duration_hours: int = DEFAULT_BREAK_GLASS_HOURS


class BreakGlassDecision(BaseModel):
    notes: Optional[str] = None


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_data = getattr(request.state, "user", None)
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = user_data.get("id")
    tenant_id = user_data.get("tenant_id")
    result = await db.execute(
        select(User).where(and_(User.id == user_id, User.tenant_id == tenant_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/accounts")
async def list_privileged_accounts(
    account_type: Optional[str] = Query(None),
    system_name: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(PrivilegedAccount).where(
        and_(
            PrivilegedAccount.tenant_id == current_user.tenant_id,
            PrivilegedAccount.deleted_at.is_(None),
        )
    )
    if account_type:
        query = query.where(PrivilegedAccount.account_type == account_type)
    if system_name:
        query = query.where(PrivilegedAccount.system_name.ilike(f"%{system_name}%"))
    if risk_level:
        query = query.where(PrivilegedAccount.risk_level == risk_level)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(PrivilegedAccount.system_name).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    accounts = rows.scalars().all()

    return {
        "items": [a.to_dict() for a in accounts],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
async def create_privileged_account(
    data: PrivilegedAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = PrivilegedAccount(
        tenant_id=current_user.tenant_id,
        account_name=data.account_name,
        account_type=data.account_type,
        system_name=data.system_name,
        owner_id=data.owner_id,
        risk_level=data.risk_level,
        is_vaulted=data.is_vaulted,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "pam.account.create",
        "privileged_account",
        str(account.id),
        {"account_name": data.account_name, "system_name": data.system_name},
        ip_address=request.client.host if request.client else None,
        risk_level="medium",
    )
    return account.to_dict()


@router.get("/accounts/{account_id}")
async def get_privileged_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PrivilegedAccount).where(
            and_(
                PrivilegedAccount.id == account_id,
                PrivilegedAccount.tenant_id == current_user.tenant_id,
                PrivilegedAccount.deleted_at.is_(None),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account.to_dict()


@router.put("/accounts/{account_id}")
async def update_privileged_account(
    account_id: UUID,
    data: PrivilegedAccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PrivilegedAccount).where(
            and_(
                PrivilegedAccount.id == account_id,
                PrivilegedAccount.tenant_id == current_user.tenant_id,
                PrivilegedAccount.deleted_at.is_(None),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if data.account_name is not None:
        account.account_name = data.account_name
    if data.account_type is not None:
        account.account_type = data.account_type
    if data.system_name is not None:
        account.system_name = data.system_name
    if data.owner_id is not None:
        account.owner_id = data.owner_id
    if data.risk_level is not None:
        account.risk_level = data.risk_level
    if data.is_vaulted is not None:
        account.is_vaulted = data.is_vaulted

    await db.commit()
    return account.to_dict()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def request_privileged_session(
    data: SessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify account exists
    acc_result = await db.execute(
        select(PrivilegedAccount).where(
            and_(
                PrivilegedAccount.id == data.privileged_account_id,
                PrivilegedAccount.tenant_id == current_user.tenant_id,
                PrivilegedAccount.deleted_at.is_(None),
            )
        )
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Privileged account not found")

    if not data.justification or len(data.justification.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Justification must be at least 10 characters",
        )

    now = datetime.now(timezone.utc)
    session = PAMSession(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        privileged_account_id=data.privileged_account_id,
        session_type=data.session_type,
        justification=data.justification,
        status="active",
        started_at=now,
        expires_at=now + timedelta(hours=data.duration_hours),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "pam.session.create",
        "pam_session",
        str(session.id),
        {
            "privileged_account_id": str(data.privileged_account_id),
            "account_name": account.account_name,
            "system": account.system_name,
            "justification": data.justification,
        },
        ip_address=request.client.host if request.client else None,
        risk_level="high",
    )
    return session.to_dict()


@router.get("/sessions")
async def list_pam_sessions(
    session_status: Optional[str] = Query(None, alias="status"),
    user_id: Optional[UUID] = Query(None),
    privileged_account_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(PAMSession).where(PAMSession.tenant_id == current_user.tenant_id)
    if session_status:
        query = query.where(PAMSession.status == session_status)
    else:
        query = query.where(PAMSession.status == "active")
    if user_id:
        query = query.where(PAMSession.user_id == user_id)
    if privileged_account_id:
        query = query.where(PAMSession.privileged_account_id == privileged_account_id)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(PAMSession.started_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    sessions = rows.scalars().all()

    return {
        "items": [s.to_dict() for s in sessions],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/sessions/{session_id}")
async def terminate_pam_session(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PAMSession).where(
            and_(
                PAMSession.id == session_id,
                PAMSession.tenant_id == current_user.tenant_id,
            )
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is already {session.status}")

    session.status = "terminated"
    session.terminated_at = datetime.now(timezone.utc)
    await db.commit()

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "pam.session.terminate",
        "pam_session",
        str(session_id),
        {"terminated_by": str(current_user.id)},
        ip_address=request.client.host if request.client else None,
        risk_level="medium",
    )
    return {"success": True, "session_id": str(session_id), "status": "terminated"}


@router.post("/break-glass", status_code=status.HTTP_201_CREATED)
async def submit_break_glass_request(
    data: BreakGlassCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify account exists
    acc_result = await db.execute(
        select(PrivilegedAccount).where(
            and_(
                PrivilegedAccount.id == data.privileged_account_id,
                PrivilegedAccount.tenant_id == current_user.tenant_id,
                PrivilegedAccount.deleted_at.is_(None),
            )
        )
    )
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Privileged account not found")

    if len(data.justification.strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="Break-glass justification must be at least 20 characters",
        )

    bg_request = BreakGlassRequest(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        privileged_account_id=data.privileged_account_id,
        justification=data.justification,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=data.duration_hours),
    )
    db.add(bg_request)
    await db.commit()
    await db.refresh(bg_request)

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "pam.break_glass.request",
        "break_glass_request",
        str(bg_request.id),
        {
            "privileged_account_id": str(data.privileged_account_id),
            "justification": data.justification,
        },
        ip_address=request.client.host if request.client else None,
        risk_level="critical",
    )
    return bg_request.to_dict()


@router.get("/break-glass")
async def list_break_glass_requests(
    bg_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(BreakGlassRequest).where(
        BreakGlassRequest.tenant_id == current_user.tenant_id
    )
    if bg_status:
        query = query.where(BreakGlassRequest.status == bg_status)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(BreakGlassRequest.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    requests = rows.scalars().all()

    return {
        "items": [r.to_dict() for r in requests],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/break-glass/{request_id}/approve")
async def approve_break_glass_request(
    request_id: UUID,
    data: BreakGlassDecision,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only tenant admins can approve break-glass requests")

    result = await db.execute(
        select(BreakGlassRequest).where(
            and_(
                BreakGlassRequest.id == request_id,
                BreakGlassRequest.tenant_id == current_user.tenant_id,
            )
        )
    )
    bg_request = result.scalar_one_or_none()
    if not bg_request:
        raise HTTPException(status_code=404, detail="Break-glass request not found")
    if bg_request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {bg_request.status}")

    bg_request.status = "approved"
    bg_request.approved_by = current_user.id
    bg_request.approved_at = datetime.now(timezone.utc)
    await db.commit()

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "pam.break_glass.approve",
        "break_glass_request",
        str(request_id),
        {"approved_by": str(current_user.id), "notes": data.notes},
        ip_address=request.client.host if request.client else None,
        risk_level="critical",
    )
    return bg_request.to_dict()


@router.post("/break-glass/{request_id}/deny")
async def deny_break_glass_request(
    request_id: UUID,
    data: BreakGlassDecision,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only tenant admins can deny break-glass requests")

    result = await db.execute(
        select(BreakGlassRequest).where(
            and_(
                BreakGlassRequest.id == request_id,
                BreakGlassRequest.tenant_id == current_user.tenant_id,
            )
        )
    )
    bg_request = result.scalar_one_or_none()
    if not bg_request:
        raise HTTPException(status_code=404, detail="Break-glass request not found")
    if bg_request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {bg_request.status}")

    # Use "expired" status since the model only has pending/approved/active/expired
    bg_request.status = "expired"
    bg_request.approved_by = current_user.id
    bg_request.approved_at = datetime.now(timezone.utc)
    await db.commit()

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "pam.break_glass.deny",
        "break_glass_request",
        str(request_id),
        {"denied_by": str(current_user.id), "notes": data.notes},
        ip_address=request.client.host if request.client else None,
        risk_level="high",
    )
    return bg_request.to_dict()


@router.get("/stats")
async def get_pam_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    now = datetime.now(timezone.utc)

    active_sessions = await db.execute(
        select(func.count(PAMSession.id)).where(
            and_(PAMSession.tenant_id == tenant_id, PAMSession.status == "active")
        )
    )

    expiring_soon = await db.execute(
        select(func.count(PAMSession.id)).where(
            and_(
                PAMSession.tenant_id == tenant_id,
                PAMSession.status == "active",
                PAMSession.expires_at <= now + timedelta(hours=1),
                PAMSession.expires_at > now,
            )
        )
    )

    pending_break_glass = await db.execute(
        select(func.count(BreakGlassRequest.id)).where(
            and_(
                BreakGlassRequest.tenant_id == tenant_id,
                BreakGlassRequest.status == "pending",
            )
        )
    )

    total_accounts = await db.execute(
        select(func.count(PrivilegedAccount.id)).where(
            and_(
                PrivilegedAccount.tenant_id == tenant_id,
                PrivilegedAccount.deleted_at.is_(None),
            )
        )
    )

    critical_accounts = await db.execute(
        select(func.count(PrivilegedAccount.id)).where(
            and_(
                PrivilegedAccount.tenant_id == tenant_id,
                PrivilegedAccount.risk_level == "critical",
                PrivilegedAccount.deleted_at.is_(None),
            )
        )
    )

    return {
        "active_sessions": active_sessions.scalar(),
        "expiring_soon": expiring_soon.scalar(),
        "pending_break_glass": pending_break_glass.scalar(),
        "total_privileged_accounts": total_accounts.scalar(),
        "critical_accounts": critical_accounts.scalar(),
    }
