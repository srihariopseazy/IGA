from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info

from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.application import Application, Entitlement
from backend.models.access_request import AccessRequest
from backend.models.risk import RiskScore


@strawberry.type
class UserType:
    id: strawberry.ID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime


@strawberry.type
class ApplicationType:
    id: strawberry.ID
    name: str
    description: Optional[str]
    is_active: bool


@strawberry.type
class EntitlementType:
    id: strawberry.ID
    name: str
    application_id: strawberry.ID
    risk_level: str


@strawberry.type
class AccessRequestType:
    id: strawberry.ID
    requester_id: strawberry.ID
    status: str
    created_at: datetime
    business_justification: Optional[str]


@strawberry.type
class RiskScoreType:
    id: strawberry.ID
    user_id: strawberry.ID
    overall_score: float
    risk_level: str
    calculated_at: datetime


@strawberry.type
class Query:
    @strawberry.field
    async def users(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
    ) -> List[UserType]:
        request = info.context["request"]
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return []

        async for db in get_db():
            result = await db.execute(
                select(User)
                .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
                .limit(limit)
                .offset(offset)
            )
            users = result.scalars().all()
            return [
                UserType(
                    id=strawberry.ID(str(u.id)),
                    email=u.email,
                    full_name=u.full_name,
                    is_active=u.is_active,
                    created_at=u.created_at,
                )
                for u in users
            ]
        return []

    @strawberry.field
    async def user(self, info: Info, id: strawberry.ID) -> Optional[UserType]:
        request = info.context["request"]
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return None

        async for db in get_db():
            result = await db.execute(
                select(User).where(
                    User.id == uuid.UUID(str(id)),
                    User.tenant_id == tenant_id,
                    User.deleted_at.is_(None),
                )
            )
            u = result.scalar_one_or_none()
            if not u:
                return None
            return UserType(
                id=strawberry.ID(str(u.id)),
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                created_at=u.created_at,
            )
        return None

    @strawberry.field
    async def applications(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ApplicationType]:
        request = info.context["request"]
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return []

        async for db in get_db():
            result = await db.execute(
                select(Application)
                .where(Application.tenant_id == tenant_id, Application.deleted_at.is_(None))
                .limit(limit)
                .offset(offset)
            )
            apps = result.scalars().all()
            return [
                ApplicationType(
                    id=strawberry.ID(str(a.id)),
                    name=a.name,
                    description=a.description,
                    is_active=a.is_active,
                )
                for a in apps
            ]
        return []

    @strawberry.field
    async def risk_scores(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
    ) -> List[RiskScoreType]:
        request = info.context["request"]
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return []

        async for db in get_db():
            result = await db.execute(
                select(RiskScore)
                .where(RiskScore.tenant_id == tenant_id)
                .order_by(RiskScore.overall_score.desc())
                .limit(limit)
                .offset(offset)
            )
            scores = result.scalars().all()
            return [
                RiskScoreType(
                    id=strawberry.ID(str(s.id)),
                    user_id=strawberry.ID(str(s.user_id)),
                    overall_score=float(s.overall_score),
                    risk_level=s.risk_level,
                    calculated_at=s.calculated_at,
                )
                for s in scores
            ]
        return []


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def placeholder(self) -> bool:
        return True


schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema, context_getter=lambda request: {"request": request})
