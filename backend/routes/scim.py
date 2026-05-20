"""
SCIM 2.0 provider implementation following RFC 7644.
Authentication uses Bearer token from connector config (not JWT).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.rbac import Role, UserRole
from backend.models.user import User

router = APIRouter(prefix="/scim/v2", tags=["SCIM 2.0"])

SCIM_CONTENT_TYPE = "application/scim+json"
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


class SCIMUserName(BaseModel):
    givenName: Optional[str] = None
    familyName: Optional[str] = None
    formatted: Optional[str] = None


class SCIMEmail(BaseModel):
    value: str
    primary: bool = False
    type: str = "work"


class SCIMUserCreate(BaseModel):
    schemas: List[str] = [SCIM_USER_SCHEMA]
    userName: str
    name: Optional[SCIMUserName] = None
    emails: Optional[List[SCIMEmail]] = None
    active: bool = True
    displayName: Optional[str] = None
    externalId: Optional[str] = None


class SCIMPatchOp(BaseModel):
    op: str  # add, remove, replace
    path: Optional[str] = None
    value: Optional[Any] = None


class SCIMPatch(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    Operations: List[SCIMPatchOp]


class SCIMGroupCreate(BaseModel):
    schemas: List[str] = [SCIM_GROUP_SCHEMA]
    displayName: str
    externalId: Optional[str] = None
    members: Optional[List[Dict[str, str]]] = None


async def _get_scim_tenant(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    Authenticate SCIM request via Bearer token.
    Token corresponds to a ConnectorConfig entry with config_key='scim_token'.
    Returns tenant_id string.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "schemas": [SCIM_ERROR_SCHEMA],
                "status": "401",
                "detail": "Authorization required",
            },
        )
    token = authorization[len("Bearer "):].strip()

    try:
        from backend.models.connector import ConnectorConfig
        from backend.utils.security import decrypt_field
        from backend.config import settings
        import base64

        result = await db.execute(
            select(ConnectorConfig).where(ConnectorConfig.config_key == "scim_token")
        )
        configs = result.scalars().all()

        encryption_key = base64.b64decode(settings.ENCRYPTION_KEY)
        for cfg in configs:
            raw_val = cfg.config_value_encrypted or ""
            if raw_val.startswith("enc:"):
                try:
                    decrypted = decrypt_field(raw_val[4:], encryption_key)
                except Exception:
                    decrypted = raw_val[4:]
            else:
                decrypted = raw_val
            if decrypted == token:
                return str(cfg.tenant_id)
    except Exception:
        pass

    raise HTTPException(
        status_code=401,
        detail={
            "schemas": [SCIM_ERROR_SCHEMA],
            "status": "401",
            "detail": "Invalid token",
        },
    )


def _user_to_scim(user: User) -> Dict[str, Any]:
    name_dict: Dict[str, str] = {}
    if user.first_name:
        name_dict["givenName"] = user.first_name
    if user.last_name:
        name_dict["familyName"] = user.last_name
    if user.display_name:
        name_dict["formatted"] = user.display_name
    elif user.first_name or user.last_name:
        name_dict["formatted"] = f"{user.first_name or ''} {user.last_name or ''}".strip()

    created_at = user.created_at.isoformat() if user.created_at else None
    updated_at = user.updated_at.isoformat() if user.updated_at else None

    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(user.id),
        "externalId": user.employee_id,
        "userName": user.email,
        "name": name_dict,
        "displayName": user.display_name or f"{user.first_name or ''} {user.last_name or ''}".strip(),
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": user.status == "active",
        "phoneNumbers": [{"value": user.phone, "primary": True}] if user.phone else [],
        "meta": {
            "resourceType": "User",
            "created": created_at,
            "lastModified": updated_at,
            "location": f"/scim/v2/Users/{user.id}",
        },
    }


def _role_to_scim_group(role: Role) -> Dict[str, Any]:
    created_at = role.created_at.isoformat() if role.created_at else None
    updated_at = role.updated_at.isoformat() if role.updated_at else None
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": str(role.id),
        "displayName": role.name,
        "meta": {
            "resourceType": "Group",
            "created": created_at,
            "lastModified": updated_at,
            "location": f"/scim/v2/Groups/{role.id}",
        },
    }


def _scim_list_response(resources: List[dict], total: int, start_index: int, count: int) -> dict:
    return {
        "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": count,
        "Resources": resources,
    }


@router.get("/Users")
async def scim_list_users(
    filter: Optional[str] = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    query = select(User).where(
        and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
    )

    # Basic SCIM filter support: userName eq "value"
    if filter:
        filter_lower = filter.lower().strip()
        if "username eq " in filter_lower:
            val = filter.split('"')[1] if '"' in filter else filter.split("'")[1]
            query = query.where(User.email == val)
        elif "externalid eq " in filter_lower:
            val = filter.split('"')[1] if '"' in filter else filter.split("'")[1]
            query = query.where(User.employee_id == val)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset(startIndex - 1).limit(count)
    rows = await db.execute(query)
    users = rows.scalars().all()

    return _scim_list_response(
        [_user_to_scim(u) for u in users],
        total=total,
        start_index=startIndex,
        count=count,
    )


@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def scim_create_user(
    data: SCIMUserCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    # Determine email from userName or emails list
    email = data.userName
    if data.emails:
        primary_emails = [e for e in data.emails if e.primary]
        if primary_emails:
            email = primary_emails[0].value

    # Check if user already exists
    existing = await db.execute(
        select(User).where(and_(User.tenant_id == tenant_id, User.email == email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={
                "schemas": [SCIM_ERROR_SCHEMA],
                "status": "409",
                "detail": f"User with userName '{email}' already exists",
                "scimType": "uniqueness",
            },
        )

    first_name = data.name.givenName if data.name else None
    last_name = data.name.familyName if data.name else None
    display_name = data.name.formatted if data.name else data.displayName

    user = User(
        tenant_id=tenant_id,
        email=email,
        username=email,
        first_name=first_name,
        last_name=last_name,
        display_name=display_name,
        employee_id=data.externalId,
        status="active" if data.active else "inactive",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return JSONResponse(
        content=_user_to_scim(user),
        status_code=201,
        media_type=SCIM_CONTENT_TYPE,
    )


@router.get("/Users/{user_id}")
async def scim_get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "User not found"},
        )
    return JSONResponse(content=_user_to_scim(user), media_type=SCIM_CONTENT_TYPE)


@router.put("/Users/{user_id}")
async def scim_replace_user(
    user_id: str,
    data: SCIMUserCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "User not found"},
        )

    if data.name:
        user.first_name = data.name.givenName
        user.last_name = data.name.familyName
        user.display_name = data.name.formatted
    if data.displayName:
        user.display_name = data.displayName
    if data.externalId is not None:
        user.employee_id = data.externalId
    user.status = "active" if data.active else "inactive"

    await db.commit()
    await db.refresh(user)
    return JSONResponse(content=_user_to_scim(user), media_type=SCIM_CONTENT_TYPE)


@router.patch("/Users/{user_id}")
async def scim_patch_user(
    user_id: str,
    data: SCIMPatch,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "User not found"},
        )

    for op in data.Operations:
        op_lower = op.op.lower()
        if op.path == "active" or (not op.path and isinstance(op.value, dict) and "active" in op.value):
            active_val = op.value if op.path == "active" else op.value.get("active")
            if op_lower in ("add", "replace"):
                user.status = "active" if active_val else "inactive"
            elif op_lower == "remove":
                user.status = "inactive"
        elif op.path == "name.givenName" and op_lower in ("add", "replace"):
            user.first_name = op.value
        elif op.path == "name.familyName" and op_lower in ("add", "replace"):
            user.last_name = op.value
        elif op.path == "displayName" and op_lower in ("add", "replace"):
            user.display_name = op.value
        elif not op.path and isinstance(op.value, dict):
            # Generic attribute replacement
            if "name" in op.value and isinstance(op.value["name"], dict):
                user.first_name = op.value["name"].get("givenName", user.first_name)
                user.last_name = op.value["name"].get("familyName", user.last_name)
            if "displayName" in op.value:
                user.display_name = op.value["displayName"]
            if "active" in op.value:
                user.status = "active" if op.value["active"] else "inactive"

    await db.commit()
    await db.refresh(user)
    return JSONResponse(content=_user_to_scim(user), media_type=SCIM_CONTENT_TYPE)


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def scim_delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "User not found"},
        )
    user.soft_delete()
    user.status = "inactive"
    await db.commit()


@router.get("/Groups")
async def scim_list_groups(
    filter: Optional[str] = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    query = select(Role).where(
        and_(Role.tenant_id == tenant_id, Role.deleted_at.is_(None))
    )
    if filter:
        filter_lower = filter.lower().strip()
        if "displayname eq " in filter_lower:
            val = filter.split('"')[1] if '"' in filter else filter.split("'")[1]
            query = query.where(Role.name == val)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset(startIndex - 1).limit(count)
    rows = await db.execute(query)
    roles = rows.scalars().all()

    return _scim_list_response(
        [_role_to_scim_group(r) for r in roles],
        total=total,
        start_index=startIndex,
        count=count,
    )


@router.post("/Groups", status_code=status.HTTP_201_CREATED)
async def scim_create_group(
    data: SCIMGroupCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    role = Role(
        tenant_id=tenant_id,
        name=data.displayName,
        role_type="business",
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return JSONResponse(
        content=_role_to_scim_group(role),
        status_code=201,
        media_type=SCIM_CONTENT_TYPE,
    )


@router.get("/Groups/{group_id}")
async def scim_get_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(Role).where(
            and_(Role.id == group_id, Role.tenant_id == tenant_id, Role.deleted_at.is_(None))
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "Group not found"},
        )

    group_dict = _role_to_scim_group(role)

    # Load members
    members_result = await db.execute(
        select(UserRole.user_id).where(
            and_(UserRole.role_id == group_id, UserRole.deleted_at.is_(None))
        )
    )
    member_ids = [str(r[0]) for r in members_result.all()]
    group_dict["members"] = [{"value": uid, "$ref": f"/scim/v2/Users/{uid}"} for uid in member_ids]

    return JSONResponse(content=group_dict, media_type=SCIM_CONTENT_TYPE)


@router.put("/Groups/{group_id}")
async def scim_replace_group(
    group_id: str,
    data: SCIMGroupCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(Role).where(
            and_(Role.id == group_id, Role.tenant_id == tenant_id, Role.deleted_at.is_(None))
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "Group not found"},
        )

    role.name = data.displayName
    await db.commit()
    await db.refresh(role)
    return JSONResponse(content=_role_to_scim_group(role), media_type=SCIM_CONTENT_TYPE)


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def scim_delete_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(_get_scim_tenant),
):
    result = await db.execute(
        select(Role).where(
            and_(Role.id == group_id, Role.tenant_id == tenant_id, Role.deleted_at.is_(None))
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(
            status_code=404,
            detail={"schemas": [SCIM_ERROR_SCHEMA], "status": "404", "detail": "Group not found"},
        )
    role.soft_delete()
    await db.commit()


@router.get("/ServiceProviderConfig")
async def scim_service_provider_config():
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://tools.ietf.org/html/rfc7644",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 1000},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer Token",
                "description": "Authentication scheme using the OAuth Bearer Token standard",
                "specUri": "https://tools.ietf.org/html/rfc6750",
                "primary": True,
            }
        ],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": "/scim/v2/ServiceProviderConfig",
        },
    }


@router.get("/Schemas")
async def scim_schemas():
    return {
        "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
        "totalResults": 2,
        "itemsPerPage": 2,
        "startIndex": 1,
        "Resources": [
            {
                "id": SCIM_USER_SCHEMA,
                "name": "User",
                "description": "SCIM User",
                "attributes": [
                    {"name": "id", "type": "string", "required": True, "mutability": "readOnly"},
                    {"name": "userName", "type": "string", "required": True, "mutability": "readWrite"},
                    {"name": "name", "type": "complex", "required": False, "mutability": "readWrite"},
                    {"name": "emails", "type": "complex", "multiValued": True, "required": False, "mutability": "readWrite"},
                    {"name": "active", "type": "boolean", "required": False, "mutability": "readWrite"},
                    {"name": "displayName", "type": "string", "required": False, "mutability": "readWrite"},
                    {"name": "externalId", "type": "string", "required": False, "mutability": "readWrite"},
                ],
            },
            {
                "id": SCIM_GROUP_SCHEMA,
                "name": "Group",
                "description": "SCIM Group",
                "attributes": [
                    {"name": "id", "type": "string", "required": True, "mutability": "readOnly"},
                    {"name": "displayName", "type": "string", "required": True, "mutability": "readWrite"},
                    {"name": "members", "type": "complex", "multiValued": True, "required": False, "mutability": "readWrite"},
                    {"name": "externalId", "type": "string", "required": False, "mutability": "readWrite"},
                ],
            },
        ],
    }


@router.get("/ResourceTypes")
async def scim_resource_types():
    return {
        "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
        "totalResults": 2,
        "itemsPerPage": 2,
        "startIndex": 1,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "description": "User Account",
                "schema": SCIM_USER_SCHEMA,
                "meta": {"resourceType": "ResourceType", "location": "/scim/v2/ResourceTypes/User"},
            },
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "Group",
                "name": "Group",
                "endpoint": "/Groups",
                "description": "Group",
                "schema": SCIM_GROUP_SCHEMA,
                "meta": {"resourceType": "ResourceType", "location": "/scim/v2/ResourceTypes/Group"},
            },
        ],
    }
