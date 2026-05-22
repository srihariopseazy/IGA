from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from backend.database import get_db
from backend.middleware.auth import get_current_user
from backend.models.user import User

router = APIRouter(prefix="/sync-jobs", tags=["Sync Jobs"])


@router.get("")
async def list_sync_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List HRMS sync jobs for the tenant."""
    from backend.models.sync import HRMSSyncJob
    query = select(HRMSSyncJob).where(
        HRMSSyncJob.tenant_id == current_user.tenant_id
    ).order_by(HRMSSyncJob.created_at.desc())
    count_query = select(func.count(HRMSSyncJob.id)).where(
        HRMSSyncJob.tenant_id == current_user.tenant_id
    )
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    jobs = result.scalars().all()
    return {
        "items": [
            {
                "id": str(j.id),
                "status": j.status,
                "records_processed": j.records_processed,
                "records_created": j.records_created,
                "records_updated": j.records_updated,
                "records_failed": j.records_failed,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
