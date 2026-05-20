from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.notification import Notification
from backend.models.user import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


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


@router.get("/")
async def list_notifications(
    unread_only: bool = Query(False),
    notification_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Notification).where(
        and_(
            Notification.user_id == current_user.id,
            Notification.tenant_id == current_user.tenant_id,
        )
    )
    if unread_only:
        query = query.where(Notification.is_read == False)  # noqa: E712
    if notification_type:
        query = query.where(Notification.notification_type == notification_type)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    # Unread first, then by created_at desc
    query = query.order_by(Notification.is_read.asc(), desc(Notification.created_at))
    query = query.offset((page - 1) * per_page).limit(per_page)

    rows = await db.execute(query)
    notifications = rows.scalars().all()

    return {
        "items": [n.to_dict() for n in notifications],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/unread-count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(func.count(Notification.id)).where(
            and_(
                Notification.user_id == current_user.id,
                Notification.tenant_id == current_user.tenant_id,
                Notification.is_read == False,  # noqa: E712
            )
        )
    )
    count = result.scalar() or 0
    return {"unread_count": count}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.user_id == current_user.id,
                Notification.tenant_id == current_user.tenant_id,
            )
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()

    return notification.to_dict()


@router.post("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.user_id == current_user.id,
                Notification.tenant_id == current_user.tenant_id,
                Notification.is_read == False,  # noqa: E712
            )
        )
    )
    notifications = result.scalars().all()

    now = datetime.now(timezone.utc)
    count = 0
    for n in notifications:
        n.is_read = True
        n.read_at = now
        count += 1

    if count > 0:
        await db.commit()

    return {"success": True, "marked_count": count}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.user_id == current_user.id,
                Notification.tenant_id == current_user.tenant_id,
            )
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    await db.delete(notification)
    await db.commit()
    return {"success": True}
