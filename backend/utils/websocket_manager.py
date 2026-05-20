import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Set, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections with tenant isolation.
    Connections are stored per-tenant to enforce data boundaries.
    """

    def __init__(self) -> None:
        # tenant_id -> {user_id -> WebSocket}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # tenant_id -> set of user_ids
        self.tenant_rooms: Dict[str, Set[str]] = {}

    async def connect(
        self, websocket: WebSocket, tenant_id: str, user_id: str
    ) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = {}
            self.tenant_rooms[tenant_id] = set()
        self.active_connections[tenant_id][user_id] = websocket
        self.tenant_rooms[tenant_id].add(user_id)
        logger.info(
            "WebSocket connected: tenant=%s user=%s (total in tenant: %d)",
            tenant_id,
            user_id,
            len(self.tenant_rooms[tenant_id]),
        )
        await self.send_personal_message(
            {
                "type": "connected",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            tenant_id,
            user_id,
        )

    async def disconnect(self, tenant_id: str, user_id: str) -> None:
        """Remove a WebSocket connection."""
        if tenant_id in self.active_connections:
            self.active_connections[tenant_id].pop(user_id, None)
            self.tenant_rooms.get(tenant_id, set()).discard(user_id)
            if not self.active_connections[tenant_id]:
                del self.active_connections[tenant_id]
                self.tenant_rooms.pop(tenant_id, None)
        logger.info("WebSocket disconnected: tenant=%s user=%s", tenant_id, user_id)

    async def send_personal_message(
        self, message: dict, tenant_id: str, user_id: str
    ) -> None:
        """Send a message to a specific user in a tenant."""
        tenant_sockets = self.active_connections.get(tenant_id, {})
        websocket = tenant_sockets.get(user_id)
        if websocket is None:
            return
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as exc:
            logger.warning(
                "Failed to send message to tenant=%s user=%s: %s", tenant_id, user_id, exc
            )
            await self.disconnect(tenant_id, user_id)

    async def broadcast_to_tenant(self, message: dict, tenant_id: str) -> None:
        """Broadcast a message to all connected users in a tenant."""
        tenant_sockets = self.active_connections.get(tenant_id, {})
        if not tenant_sockets:
            return
        payload = json.dumps(message)
        dead_users = []
        for user_id, websocket in list(tenant_sockets.items()):
            try:
                await websocket.send_text(payload)
            except Exception as exc:
                logger.warning(
                    "Failed to broadcast to tenant=%s user=%s: %s", tenant_id, user_id, exc
                )
                dead_users.append(user_id)
        for user_id in dead_users:
            await self.disconnect(tenant_id, user_id)

    async def broadcast_risk_alert(
        self,
        tenant_id: str,
        user_id: str,
        risk_score: float,
        reason: str,
    ) -> None:
        """Send a risk score alert to a specific user and admin broadcast."""
        message = {
            "type": "risk_alert",
            "user_id": user_id,
            "risk_score": risk_score,
            "reason": reason,
            "severity": "critical" if risk_score >= 80 else "high" if risk_score >= 60 else "medium",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_personal_message(message, tenant_id, user_id)

    async def broadcast_approval_notification(
        self,
        tenant_id: str,
        approver_id: str,
        request_id: str,
        requester_name: str,
    ) -> None:
        """Notify an approver that a new access request requires their review."""
        message = {
            "type": "approval_required",
            "request_id": request_id,
            "requester_name": requester_name,
            "message": f"{requester_name} has submitted an access request requiring your approval.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_personal_message(message, tenant_id, approver_id)

    async def broadcast_certification_alert(
        self,
        tenant_id: str,
        reviewer_id: str,
        campaign_name: str,
        items_count: int,
    ) -> None:
        """Notify a reviewer that certification items are pending."""
        message = {
            "type": "certification_alert",
            "campaign_name": campaign_name,
            "items_count": items_count,
            "message": f"You have {items_count} items pending review in '{campaign_name}'.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_personal_message(message, tenant_id, reviewer_id)

    async def send_provisioning_update(
        self,
        tenant_id: str,
        user_id: str,
        task_id: str,
        status: str,
    ) -> None:
        """Send a provisioning task status update to the target user."""
        message = {
            "type": "provisioning_update",
            "task_id": task_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_personal_message(message, tenant_id, user_id)

    async def ping_all(self) -> None:
        """Send a ping to all connected clients to detect stale connections."""
        payload = json.dumps({"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
        dead: list = []
        for tenant_id, user_sockets in list(self.active_connections.items()):
            for user_id, websocket in list(user_sockets.items()):
                try:
                    await websocket.send_text(payload)
                except Exception:
                    dead.append((tenant_id, user_id))
        for tenant_id, user_id in dead:
            await self.disconnect(tenant_id, user_id)

    def connection_count(self, tenant_id: Optional[str] = None) -> int:
        """Return count of active connections, optionally scoped to tenant."""
        if tenant_id:
            return len(self.active_connections.get(tenant_id, {}))
        return sum(len(users) for users in self.active_connections.values())


ws_manager = ConnectionManager()
