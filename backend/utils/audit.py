"""Lightweight audit helper used by route handlers."""
from __future__ import annotations

from typing import Any, Optional


async def log_action(
    *args: Any,
    **kwargs: Any,
) -> None:
    """No-op stub; full audit logging goes through AuditLogger / audit_logger."""
    pass
