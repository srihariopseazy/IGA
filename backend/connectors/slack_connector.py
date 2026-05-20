"""
Slack Connector for IGA Platform.
Uses the Slack Web API with Bot Token authentication.
Supports user lookup, deactivation, channel management, and invitations.

Required bot token scopes:
  - users:read, users:read.email
  - channels:read, conversations:read, conversations.members:read
  - conversations:write (for inviting to channels)

Admin operations (invite/deactivate) require a user token with admin scopes
or Slack Enterprise Grid admin API access.
"""
import httpx
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class SlackConnector(BaseConnector):
    connector_type = "slack"
    API_BASE = "https://slack.com/api"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.bot_token = self._decrypt_config("bot_token")
        self.team_id = config.get("team_id", "")
        self.timeout = int(config.get("timeout", 30))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _form_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def _api_get(
        self, client: httpx.AsyncClient, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        resp = await client.get(
            f"{self.API_BASE}/{method}",
            headers=self._headers(),
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    async def _api_post(
        self, client: httpx.AsyncClient, method: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        resp = await client.post(
            f"{self.API_BASE}/{method}",
            headers=self._headers(),
            json=payload or {},
        )
        resp.raise_for_status()
        return resp.json()

    def _check(self, data: Dict[str, Any], operation: str) -> ConnectorResult:
        if data.get("ok"):
            return ConnectorResult(success=True, data=data)
        error = data.get("error", "unknown_error")
        return ConnectorResult(success=False, error=f"Slack API error [{operation}]: {error}")

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                data = await self._api_get(client, "auth.test")
                if data.get("ok"):
                    return ConnectorResult(
                        success=True,
                        data={
                            "team": data.get("team"),
                            "team_id": data.get("team_id"),
                            "user": data.get("user"),
                        },
                    )
                return ConnectorResult(
                    success=False, error=data.get("error", "auth.test failed")
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    async def create_user(self, user: UserAccount) -> ConnectorResult:
        """
        Invite a new user to the Slack workspace.
        Requires users.admin.invite scope (Slack Enterprise Grid or legacy admin token).
        """
        return await self.invite_user(user.email, user.first_name, user.last_name)

    async def invite_user(
        self,
        email: str,
        first_name: str = "",
        last_name: str = "",
        channel_ids: Optional[List[str]] = None,
    ) -> ConnectorResult:
        """
        Invite a user to the workspace via users.admin.invite.
        NOTE: This endpoint requires an admin/owner token, not a bot token.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                payload: Dict[str, Any] = {
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "real_name": f"{first_name} {last_name}".strip(),
                }
                if channel_ids:
                    payload["channel_ids"] = ",".join(channel_ids)
                if self.team_id:
                    payload["team_id"] = self.team_id

                resp = await client.post(
                    f"{self.API_BASE}/users.admin.invite",
                    headers=self._form_headers(),
                    data=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._check(data, "users.admin.invite")
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def update_user(
        self, external_id: str, attributes: Dict[str, Any]
    ) -> ConnectorResult:
        """Update user profile fields via users.profile.set."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                payload = {
                    "user": external_id,
                    "profile": attributes,
                }
                data = await self._api_post(client, "users.profile.set", payload)
                return self._check(data, "users.profile.set")
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        """Deactivate (soft-delete) a Slack user."""
        return await self.disable_user(external_id)

    async def enable_user(self, external_id: str) -> ConnectorResult:
        """
        Re-activate a Slack user.
        Requires users.admin.setActive and admin scope.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                payload = {"user": external_id}
                if self.team_id:
                    payload["team_id"] = self.team_id
                resp = await client.post(
                    f"{self.API_BASE}/users.admin.setActive",
                    headers=self._form_headers(),
                    data=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._check(data, "users.admin.setActive")
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def disable_user(self, external_id: str) -> ConnectorResult:
        """
        Deactivate a Slack user.
        Requires users.admin.setInactive and admin scope.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                payload = {"user": external_id}
                if self.team_id:
                    payload["team_id"] = self.team_id
                resp = await client.post(
                    f"{self.API_BASE}/users.admin.setInactive",
                    headers=self._form_headers(),
                    data=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._check(data, "users.admin.setInactive")
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def get_user(self, external_id: str) -> ConnectorResult:
        """Retrieve a Slack user by their Slack user ID."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                data = await self._api_get(
                    client, "users.info", {"user": external_id}
                )
                if data.get("ok"):
                    return ConnectorResult(
                        success=True, data=data.get("user", {})
                    )
                return ConnectorResult(
                    success=False, error=data.get("error", "unknown")
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def get_user_by_email(self, email: str) -> ConnectorResult:
        """Look up a Slack user by email address (requires users:read.email scope)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                data = await self._api_get(
                    client, "users.lookupByEmail", {"email": email}
                )
                if data.get("ok"):
                    return ConnectorResult(
                        success=True, data=data.get("user", {})
                    )
                return ConnectorResult(
                    success=False, error=data.get("error", "unknown")
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def list_users(self, filter: str = None) -> ConnectorResult:
        """List all workspace members with pagination."""
        all_members: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                while True:
                    params: Dict[str, Any] = {"limit": 200}
                    if cursor:
                        params["cursor"] = cursor
                    data = await self._api_get(client, "users.list", params)
                    if not data.get("ok"):
                        return ConnectorResult(
                            success=False,
                            error=data.get("error", "users.list failed"),
                        )
                    members = data.get("members", [])
                    # Optionally filter out bots/deleted
                    if filter == "active":
                        members = [m for m in members if not m.get("deleted") and not m.get("is_bot")]
                    all_members.extend(members)
                    cursor = (
                        data.get("response_metadata", {}).get("next_cursor") or None
                    )
                    if not cursor:
                        break
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

        return ConnectorResult(
            success=True,
            data={"users": all_members, "total": len(all_members)},
        )

    # ------------------------------------------------------------------
    # Channel operations
    # ------------------------------------------------------------------

    async def list_channels(self, types: str = "public_channel,private_channel") -> ConnectorResult:
        """List workspace channels."""
        all_channels: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                while True:
                    params: Dict[str, Any] = {"limit": 200, "types": types}
                    if cursor:
                        params["cursor"] = cursor
                    data = await self._api_get(client, "conversations.list", params)
                    if not data.get("ok"):
                        return ConnectorResult(
                            success=False,
                            error=data.get("error", "conversations.list failed"),
                        )
                    all_channels.extend(data.get("channels", []))
                    cursor = (
                        data.get("response_metadata", {}).get("next_cursor") or None
                    )
                    if not cursor:
                        break
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

        return ConnectorResult(
            success=True,
            data={"channels": all_channels, "total": len(all_channels)},
        )

    async def add_to_group(self, user_id: str, group_id: str) -> ConnectorResult:
        """Invite a user to a Slack channel (group_id = channel ID)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                data = await self._api_post(
                    client,
                    "conversations.invite",
                    {"channel": group_id, "users": user_id},
                )
                return self._check(data, "conversations.invite")
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def remove_from_group(self, user_id: str, group_id: str) -> ConnectorResult:
        """Remove a user from a Slack channel."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                data = await self._api_post(
                    client,
                    "conversations.kick",
                    {"channel": group_id, "user": user_id},
                )
                return self._check(data, "conversations.kick")
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))
