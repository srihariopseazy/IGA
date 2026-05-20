"""
Microsoft 365 Connector for IGA Platform.
Uses the Microsoft Graph API with client_credentials OAuth2 flow via httpx (no msal dependency).
"""
import httpx
import time
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class M365Connector(BaseConnector):
    connector_type = "m365"

    # Simple in-process cache keyed by "tenant_id:client_id"
    _token_cache: Dict[str, Dict[str, Any]] = {}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.tenant_id = config.get("tenant_id", "")
        self.client_id = config.get("client_id", "")
        self.client_secret = self._decrypt_config("client_secret")
        self.graph_url = "https://graph.microsoft.com/v1.0"
        self.timeout = int(config.get("timeout", 30))

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        cache_key = f"{self.tenant_id}:{self.client_id}"
        cached = self._token_cache.get(cache_key)
        if cached and time.time() < cached["expires_at"] - 60:
            return cached["token"]

        url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            token_data = resp.json()
            token = token_data["access_token"]
            expires_in = int(token_data.get("expires_in", 3600))
            self._token_cache[cache_key] = {
                "token": token,
                "expires_at": time.time() + expires_in,
            }
            return token

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.graph_url}/organization",
                    headers=self._headers(token),
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}"
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    async def create_user(self, user: UserAccount) -> ConnectorResult:
        try:
            token = await self._get_token()
            attrs = user.attributes or {}
            temp_password = attrs.get("temp_password", "TempPass123!@#")
            payload: Dict[str, Any] = {
                "accountEnabled": user.is_active,
                "displayName": f"{user.first_name} {user.last_name}",
                "givenName": user.first_name,
                "surname": user.last_name,
                "mailNickname": user.username,
                "userPrincipalName": user.email,
                "mail": user.email,
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": temp_password,
                },
            }
            # Optional department / job title
            if attrs.get("department"):
                payload["department"] = attrs["department"]
            if attrs.get("job_title"):
                payload["jobTitle"] = attrs["job_title"]
            if attrs.get("usage_location"):
                payload["usageLocation"] = attrs["usage_location"]

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.graph_url}/users",
                    headers=self._headers(token),
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return ConnectorResult(
                        success=True,
                        data={"external_id": data["id"], "user": data},
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
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.patch(
                    f"{self.graph_url}/users/{external_id}",
                    headers=self._headers(token),
                    json=attributes,
                )
                # Graph PATCH returns 204 on success
                ok = resp.status_code == 204
                return ConnectorResult(
                    success=ok,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}" if not ok else None,
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        """Soft-delete by disabling the account (Graph hard-delete moves to recycle bin for 30 days)."""
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.delete(
                    f"{self.graph_url}/users/{external_id}",
                    headers=self._headers(token),
                )
                return ConnectorResult(
                    success=resp.status_code in (204, 404)
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def enable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"accountEnabled": True})

    async def disable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"accountEnabled": False})

    async def get_user(self, external_id: str) -> ConnectorResult:
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.graph_url}/users/{external_id}",
                    headers=self._headers(token),
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def list_users(self, filter: str = None) -> ConnectorResult:
        try:
            token = await self._get_token()
            params: Dict[str, Any] = {
                "$select": (
                    "id,displayName,givenName,surname,mail,"
                    "userPrincipalName,accountEnabled,department,jobTitle"
                ),
                "$top": 100,
            }
            if filter:
                params["$filter"] = filter

            all_users: List[Dict[str, Any]] = []
            url: Optional[str] = f"{self.graph_url}/users"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                while url:
                    if url == f"{self.graph_url}/users":
                        resp = await client.get(
                            url, headers=self._headers(token), params=params
                        )
                    else:
                        # nextLink already contains encoded query params
                        resp = await client.get(
                            url, headers=self._headers(token)
                        )
                    if resp.status_code != 200:
                        return ConnectorResult(
                            success=False, error=f"HTTP {resp.status_code}"
                        )
                    data = resp.json()
                    all_users.extend(data.get("value", []))
                    url = data.get("@odata.nextLink")
                    if len(all_users) >= 1000:
                        break

            return ConnectorResult(
                success=True,
                data={"users": all_users, "total": len(all_users)},
            )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Group operations
    # ------------------------------------------------------------------

    async def add_to_group(self, user_id: str, group_id: str) -> ConnectorResult:
        try:
            token = await self._get_token()
            payload = {
                "@odata.id": f"{self.graph_url}/directoryObjects/{user_id}"
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.graph_url}/groups/{group_id}/members/$ref",
                    headers=self._headers(token),
                    json=payload,
                )
                return ConnectorResult(
                    success=resp.status_code in (200, 204)
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def remove_from_group(self, user_id: str, group_id: str) -> ConnectorResult:
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.delete(
                    f"{self.graph_url}/groups/{group_id}/members/{user_id}/$ref",
                    headers=self._headers(token),
                )
                return ConnectorResult(
                    success=resp.status_code in (200, 204, 404)
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def assign_license(
        self, user_id: str, sku_id: str
    ) -> ConnectorResult:
        """Assign an M365 license SKU to a user."""
        try:
            token = await self._get_token()
            payload = {
                "addLicenses": [{"skuId": sku_id, "disabledPlans": []}],
                "removeLicenses": [],
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.graph_url}/users/{user_id}/assignLicense",
                    headers=self._headers(token),
                    json=payload,
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        return await self.update_user(
            external_id,
            {
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": new_password,
                }
            },
        )
