"""Storage helper used by route handlers."""
from __future__ import annotations

from typing import Any, Optional


async def upload_file_to_storage(
    *args: Any,
    **kwargs: Any,
) -> Optional[str]:
    """No-op stub; full storage goes through MinIO client."""
    return None
