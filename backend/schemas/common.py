from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class BaseResponse(BaseModel):
    success: bool = True
    message: str = "OK"


class DataResponse(BaseResponse, Generic[T]):
    data: Optional[T] = None


class ListResponse(BaseResponse, Generic[T]):
    items: List[T]
    total: int
    page: int
    per_page: int
    pages: int

    @classmethod
    def create(
        cls,
        items: List[Any],
        total: int,
        page: int,
        per_page: int,
        message: str = "OK",
    ) -> "ListResponse":
        pages = math.ceil(total / per_page) if per_page > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            message=message,
        )


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    error_code: str
    details: Optional[Any] = None
    request_id: Optional[str] = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    per_page: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: str = Field(default="created_at", description="Column to sort by")
    sort_order: str = Field(
        default="desc",
        pattern="^(asc|desc)$",
        description="Sort direction: asc or desc",
    )
    search: Optional[str] = Field(default=None, description="Full-text search query")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class AuditMetadata(BaseModel):
    """Audit fields attached to create/update responses."""
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class IDResponse(BaseResponse):
    """Simple response returning the ID of a created/updated resource."""
    id: uuid.UUID


class BulkOperationResult(BaseModel):
    """Result of a bulk operation."""
    success_count: int
    failure_count: int
    errors: List[dict] = Field(default_factory=list)
