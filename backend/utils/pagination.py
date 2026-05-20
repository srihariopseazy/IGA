import base64
import json
import math
import logging
from typing import TypeVar, Generic, List, Optional, Any

from pydantic import BaseModel
from sqlalchemy import select, func, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PageInfo(BaseModel):
    has_next: bool
    has_previous: bool
    start_cursor: Optional[str] = None
    end_cursor: Optional[str] = None
    total_count: int


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    page_info: PageInfo

    model_config = {"arbitrary_types_allowed": True}


def encode_cursor(value: Any) -> str:
    """Encode a cursor value to a base64 string."""
    raw = json.dumps({"v": str(value)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> Any:
    """Decode a base64 cursor string back to its value."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return data.get("v")
    except Exception as exc:
        logger.warning("Failed to decode cursor '%s': %s", cursor, exc)
        return None


async def paginate_query(
    session: AsyncSession,
    model,
    cursor: Optional[str] = None,
    limit: int = 20,
    order_by: str = "created_at",
    order_dir: str = "desc",
    filters: Optional[list] = None,
) -> PaginatedResponse:
    """
    Cursor-based pagination for SQLAlchemy async queries.

    Args:
        session: AsyncSession
        model: SQLAlchemy model class
        cursor: encoded cursor from previous page (end_cursor or start_cursor)
        limit: page size (max items to return)
        order_by: column name to sort by
        order_dir: 'asc' or 'desc'
        filters: list of SQLAlchemy filter expressions

    Returns:
        PaginatedResponse with items and page_info
    """
    sort_column = getattr(model, order_by, model.created_at)
    direction = desc if order_dir.lower() == "desc" else asc

    # Count total
    count_stmt = select(func.count()).select_from(model)
    if filters:
        for f in filters:
            count_stmt = count_stmt.where(f)
    total_count = (await session.execute(count_stmt)).scalar() or 0

    # Build main query
    stmt = select(model)
    if filters:
        for f in filters:
            stmt = stmt.where(f)

    # Apply cursor
    if cursor:
        cursor_value = decode_cursor(cursor)
        if cursor_value is not None:
            if order_dir.lower() == "desc":
                stmt = stmt.where(sort_column < cursor_value)
            else:
                stmt = stmt.where(sort_column > cursor_value)

    stmt = stmt.order_by(direction(sort_column)).limit(limit + 1)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    has_next = len(rows) > limit
    items = list(rows[:limit])

    # Determine has_previous (simplified: True if cursor was provided)
    has_previous = cursor is not None

    start_cursor = None
    end_cursor = None
    if items:
        start_val = getattr(items[0], order_by, None)
        end_val = getattr(items[-1], order_by, None)
        if start_val is not None:
            start_cursor = encode_cursor(start_val)
        if end_val is not None:
            end_cursor = encode_cursor(end_val)

    page_info = PageInfo(
        has_next=has_next,
        has_previous=has_previous,
        start_cursor=start_cursor,
        end_cursor=end_cursor,
        total_count=total_count,
    )

    return PaginatedResponse(items=items, page_info=page_info)


class OffsetPagination(BaseModel):
    """Standard offset-based pagination parameters."""
    page: int = 1
    per_page: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    def total_pages(self, total: int) -> int:
        if self.per_page == 0:
            return 0
        return math.ceil(total / self.per_page)
