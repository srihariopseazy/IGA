"""
SCIM 2.0 Connector for IGA Platform.
Supports bearer and basic authentication, paginated user listing, and standard SCIM operations.
"""
import httpx
import base64
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class SCIMConnector(BaseConnector):
    connector_type = "scim"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "").rstrip("/")
        self.auth_type = config.get("auth_type", "bearer")  # bearer, basic
        self.token = self._decrypt_config("token")
        self.username = config.get("username", "")
        self.password = self._decrypt_config("password")
        self.timeout = int(config.get("timeout", 30))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/scim+json",
            "Accept": "application/scim+json",
        }
        if self.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_type == "basic":
            creds = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"
        return headers

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/ServiceProviderConfig",
                    headers=self._get_headers(),
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    async def create_user(self, user: UserAccount) -> ConnectorResult:
        scim_user: Dict[str, Any] = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": user.username,
            "name": {
                "givenName": user.first_name,
                "familyName": user.last_name,
                "formatted": f"{user.first_name} {user.last_name}",
            },
            "emails": [
                {"value": user.email, "primary": True, "type": "work"}
            ],
            "active": user.is_active,
            "externalId": user.external_id,
        }
        if user.attributes:
            scim_user.update(user.attributes)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/Users",
                    headers=self._get_headers(),
                    json=scim_user,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return ConnectorResult(
                        success=True,
                        data={"external_id": data.get("id"), "scim_user": data},
                    )
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def update_user(
        self, external_id: str, attributes: Dict[str, Any]
    ) -> ConnectorResult:
        patch_ops = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": attributes}],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.patch(
                    f"{self.base_url}/Users/{external_id}",
                    headers=self._get_headers(),
                    json=patch_ops,
                )
                ok = resp.status_code in (200, 204)
                return ConnectorResult(
                    success=ok,
                    error=resp.text[:200] if not ok else None,
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.delete(
                    f"{self.base_url}/Users/{external_id}",
                    headers=self._get_headers(),
                )
                return ConnectorResult(
                    success=resp.status_code in (200, 204, 404)
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def enable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"active": True})

    async def disable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"active": False})

    async def get_user(self, external_id: str) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/Users/{external_id}",
                    headers=self._get_headers(),
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def list_users(self, filter: str = None) -> ConnectorResult:
        params: Dict[str, Any] = {"startIndex": 1, "count": 100}
        if filter:
            params["filter"] = filter

        all_users: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{self.base_url}/Users",
                        headers=self._get_headers(),
                        params=params,
                    )
                    if resp.status_code != 200:
                        return ConnectorResult(
                            success=False, error=f"HTTP {resp.status_code}"
                        )
                    data = resp.json()
                    resources = data.get("Resources", [])
                    all_users.extend(resources)
                    total = data.get("totalResults", 0)
                    if len(all_users) >= total or not resources:
                        break
                    params["startIndex"] += len(resources)
                except Exception as exc:
                    return ConnectorResult(success=False, error=str(exc))

        return ConnectorResult(
            success=True,
            data={"users": all_users, "total": len(all_users)},
        )

    # ------------------------------------------------------------------
    # Group operations
    # ------------------------------------------------------------------

    async def add_to_group(self, user_id: str, group_id: str) -> ConnectorResult:
        patch_ops = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "add",
                    "path": "members",
                    "value": [{"value": user_id}],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.patch(
                    f"{self.base_url}/Groups/{group_id}",
                    headers=self._get_headers(),
                    json=patch_ops,
                )
                ok = resp.status_code in (200, 204)
                return ConnectorResult(
                    success=ok,
                    error=resp.text[:200] if not ok else None,
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def remove_from_group(self, user_id: str, group_id: str) -> ConnectorResult:
        patch_ops = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "remove",
                    "path": f'members[value eq "{user_id}"]',
                }
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.patch(
                    f"{self.base_url}/Groups/{group_id}",
                    headers=self._get_headers(),
                    json=patch_ops,
                )
                ok = resp.status_code in (200, 204)
                return ConnectorResult(
                    success=ok,
                    error=resp.text[:200] if not ok else None,
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        return await self.update_user(external_id, {"password": new_password})
