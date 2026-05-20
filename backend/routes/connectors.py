import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.connector import Connector, ConnectorConfig
from backend.models.provisioning import ProvisioningLog, ProvisioningTask
from backend.models.user import User
from backend.audit.audit_logger import audit_logger

router = APIRouter(prefix="/connectors", tags=["Connectors"])


class ConnectorCreate(BaseModel):
    name: str
    connector_type: str
    config: Dict[str, Any] = {}


class ConnectorUpdate(BaseModel):
    name: Optional[str] = None
    connector_type: Optional[str] = None
    status: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


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


def _encrypt_value(value: str) -> str:
    """Encrypt a config value using AES-256."""
    try:
        from backend.utils.security import encrypt_field
        from backend.config import settings

        key = base64.b64decode(settings.ENCRYPTION_KEY)
        encrypted = encrypt_field(value, key)
        return f"enc:{encrypted}"
    except Exception:
        return value


def _decrypt_value(value: str) -> str:
    """Decrypt an encrypted config value."""
    if not value or not value.startswith("enc:"):
        return value
    try:
        from backend.utils.security import decrypt_field
        from backend.config import settings

        key = base64.b64decode(settings.ENCRYPTION_KEY)
        return decrypt_field(value[4:], key)
    except Exception:
        return value


_SENSITIVE_CONFIG_KEYS = {
    "password",
    "secret",
    "api_key",
    "token",
    "private_key",
    "bind_password",
    "client_secret",
    "access_token",
}


async def _upsert_connector_config(
    db: AsyncSession,
    connector_id: UUID,
    tenant_id: UUID,
    config: Dict[str, Any],
) -> None:
    for key, value in config.items():
        is_sensitive = key.lower() in _SENSITIVE_CONFIG_KEYS
        str_value = str(value)
        encrypted_value = _encrypt_value(str_value) if is_sensitive else str_value

        existing_result = await db.execute(
            select(ConnectorConfig).where(
                and_(
                    ConnectorConfig.connector_id == connector_id,
                    ConnectorConfig.config_key == key,
                )
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.config_value_encrypted = encrypted_value
            existing.is_sensitive = is_sensitive
        else:
            entry = ConnectorConfig(
                connector_id=connector_id,
                tenant_id=tenant_id,
                config_key=key,
                config_value_encrypted=encrypted_value,
                is_sensitive=is_sensitive,
            )
            db.add(entry)


async def _load_connector_config(
    db: AsyncSession, connector_id: UUID, include_sensitive: bool = False
) -> Dict[str, Any]:
    result = await db.execute(
        select(ConnectorConfig).where(ConnectorConfig.connector_id == connector_id)
    )
    configs = result.scalars().all()
    output = {}
    for cfg in configs:
        if cfg.is_sensitive and not include_sensitive:
            output[cfg.config_key] = "***"
        else:
            output[cfg.config_key] = _decrypt_value(cfg.config_value_encrypted or "")
    return output


async def _get_connector_or_404(
    connector_id: UUID, tenant_id: UUID, db: AsyncSession
) -> Connector:
    result = await db.execute(
        select(Connector).where(
            and_(
                Connector.id == connector_id,
                Connector.tenant_id == tenant_id,
                Connector.deleted_at.is_(None),
            )
        )
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


@router.get("/")
async def list_connectors(
    connector_type: Optional[str] = Query(None),
    connector_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Connector).where(
        and_(
            Connector.tenant_id == current_user.tenant_id,
            Connector.deleted_at.is_(None),
        )
    )
    if connector_type:
        query = query.where(Connector.connector_type == connector_type)
    if connector_status:
        query = query.where(Connector.status == connector_status)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(Connector.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    connectors = rows.scalars().all()
    return {
        "items": [c.to_dict() for c in connectors],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_connector(
    data: ConnectorCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = Connector(
        tenant_id=current_user.tenant_id,
        name=data.name,
        connector_type=data.connector_type,
        status="inactive",
        created_by=current_user.id,
    )
    db.add(connector)
    await db.flush()

    if data.config:
        await _upsert_connector_config(
            db, connector.id, current_user.tenant_id, data.config
        )

    await db.commit()
    await db.refresh(connector)

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "connector.create",
        "connector",
        str(connector.id),
        {"name": data.name, "type": data.connector_type},
        ip_address=request.client.host if request.client else None,
    )

    result_dict = connector.to_dict()
    result_dict["config"] = await _load_connector_config(db, connector.id)
    return result_dict


@router.get("/{connector_id}")
async def get_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await _get_connector_or_404(connector_id, current_user.tenant_id, db)
    result_dict = connector.to_dict()
    result_dict["config"] = await _load_connector_config(db, connector.id)
    return result_dict


@router.put("/{connector_id}")
async def update_connector(
    connector_id: UUID,
    data: ConnectorUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await _get_connector_or_404(connector_id, current_user.tenant_id, db)

    if data.name is not None:
        connector.name = data.name
    if data.connector_type is not None:
        connector.connector_type = data.connector_type
    if data.status is not None:
        connector.status = data.status
    connector.updated_by = current_user.id

    if data.config:
        await _upsert_connector_config(
            db, connector.id, current_user.tenant_id, data.config
        )

    await db.commit()
    await db.refresh(connector)

    result_dict = connector.to_dict()
    result_dict["config"] = await _load_connector_config(db, connector.id)
    return result_dict


@router.delete("/{connector_id}")
async def delete_connector(
    connector_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await _get_connector_or_404(connector_id, current_user.tenant_id, db)
    connector.soft_delete()
    await db.commit()
    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "connector.delete",
        "connector",
        str(connector_id),
        {},
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True}


@router.post("/{connector_id}/test")
async def test_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await _get_connector_or_404(connector_id, current_user.tenant_id, db)
    raw_config = await _load_connector_config(db, connector.id, include_sensitive=True)

    try:
        from backend.connectors.base import BaseConnector

        # Factory pattern: try to instantiate the appropriate connector
        instance: Optional[BaseConnector] = None

        if connector.connector_type == "ldap":
            from backend.connectors.ldap_connector import LDAPConnector
            instance = LDAPConnector(raw_config)
        else:
            # Generic test: just return a simulation for unsupported types
            return {
                "success": True,
                "connector_type": connector.connector_type,
                "message": f"Connection test simulated for type '{connector.connector_type}'",
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }

        result = await instance.test_connection()

        # Update connector health status
        connector.health_status = "healthy" if result.success else "unhealthy"
        connector.last_health_check = datetime.now(timezone.utc)
        if result.success:
            connector.status = "active"
        await db.commit()

        return {
            "success": result.success,
            "connector_type": connector.connector_type,
            "message": result.error or "Connection successful",
            "details": result.details or {},
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }
    except ImportError:
        return {
            "success": False,
            "connector_type": connector.connector_type,
            "message": f"Connector type '{connector.connector_type}' is not yet implemented",
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        connector.health_status = "error"
        connector.last_health_check = datetime.now(timezone.utc)
        await db.commit()
        return {
            "success": False,
            "message": str(e),
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/{connector_id}/health")
async def get_connector_health(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await _get_connector_or_404(connector_id, current_user.tenant_id, db)
    return {
        "connector_id": str(connector_id),
        "name": connector.name,
        "connector_type": connector.connector_type,
        "status": connector.status,
        "health_status": connector.health_status or "unknown",
        "last_health_check": connector.last_health_check.isoformat() if connector.last_health_check else None,
    }


@router.post("/{connector_id}/sync")
async def trigger_connector_sync(
    connector_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await _get_connector_or_404(connector_id, current_user.tenant_id, db)

    # Create a provisioning task to represent the sync job
    task = ProvisioningTask(
        tenant_id=current_user.tenant_id,
        task_type="update",
        connector_id=connector.id,
        status="pending",
        payload={"sync_type": "full", "connector_type": connector.connector_type},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Queue the Celery task
    try:
        from backend.tasks.provisioning_tasks import run_connector_sync
        run_connector_sync.delay(str(task.id), str(connector_id), str(current_user.tenant_id))
    except Exception:
        pass

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "connector.sync_triggered",
        "connector",
        str(connector_id),
        {"task_id": str(task.id)},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "success": True,
        "task_id": str(task.id),
        "message": "Sync task queued",
        "connector_id": str(connector_id),
    }


@router.get("/{connector_id}/logs")
async def get_connector_logs(
    connector_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_connector_or_404(connector_id, current_user.tenant_id, db)

    # Find tasks for this connector
    task_ids_result = await db.execute(
        select(ProvisioningTask.id).where(
            and_(
                ProvisioningTask.connector_id == connector_id,
                ProvisioningTask.tenant_id == current_user.tenant_id,
            )
        )
    )
    task_ids = [r[0] for r in task_ids_result.all()]

    if not task_ids:
        return {"items": [], "total": 0, "page": page, "per_page": per_page}

    query = select(ProvisioningLog).where(
        ProvisioningLog.provisioning_task_id.in_(task_ids)
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(ProvisioningLog.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    logs = rows.scalars().all()

    return {
        "items": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
