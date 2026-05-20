"""Notification helper used by route handlers."""
from __future__ import annotations

from typing import Any, Optional


async def notify_user(
    *args: Any,
    **kwargs: Any,
) -> None:
    """No-op stub; full notifications go through the notification service / Celery task."""
    pass
