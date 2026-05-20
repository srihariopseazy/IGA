"""
Salesforce Connector for IGA Platform.
Uses Salesforce REST API with Username-Password OAuth2 flow.
Manages Salesforce User objects via the sObject REST API and SOQL.
"""
import httpx
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class SalesforceConnector(BaseConnector):
    connector_type = "salesforce"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.instance_url = config.get("instance_url", "https://login.salesforce.com").rstrip("/")
        self.client_id = config.get("client_id", "")
        self.client_secret = self._decrypt_config("client_secret")
        self.username = config.get("username", "")
        self.password = self._decrypt_config("password")
        self.security_token = self._decrypt_config("security_token")
        self.api_version = config.get("api_version", "v58.0")
        self.timeout = int(config.get("timeout", 30))
        self._access_token: Optional[str] = None
        self._instance_url: Optional[str] = None  # returned by auth

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _authenticate(self) -> str:
        if self._access_token:
            return self._access_token

        url = f"{self.instance_url}/services/oauth2/token"
        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password + (self.security_token or ""),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            result = resp.json()
            self._access_token = result["access_token"]
            self._instance_url = result["instance_url"]
            return self._access_token

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _sf_url(self, path: str) -> str:
        base = self._instance_url or self.instance_url
        return f"{base}/services/data/{self.api_version}{path}"

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        try:
            token = await self._authenticate()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self._sf_url("/sobjects/User/describe"),
                    headers=self._headers(token),
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True)
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
        try:
            token = await self._authenticate()
            attrs = user.attributes or {}
            payload: Dict[str, Any] = {
                "Username": user.email,
                "Email": user.email,
                "FirstName": user.first_name,
                "LastName": user.last_name,
                "Alias": user.username[:8],
                "TimeZoneSidKey": attrs.get("timezone", "America/New_York"),
                "LocaleSidKey": attrs.get("locale", "en_US"),
                "EmailEncodingKey": attrs.get("email_encoding", "UTF-8"),
                "LanguageLocaleKey": attrs.get("language", "en_US"),
                "IsActive": user.is_active,
                "ProfileId": attrs.get("profile_id", ""),
                "UserRoleId": attrs.get("user_role_id") or None,
            }
            # Remove None values — Salesforce rejects null for required fields
            payload = {k: v for k, v in payload.items() if v is not None}

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._sf_url("/sobjects/User/"),
                    headers=self._headers(token),
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return ConnectorResult(
                        success=data.get("success", False),
                        data={"external_id": data.get("id")},
                        error=str(data.get("errors", [])) if not data.get("success") else None,
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
            token = await self._authenticate()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.patch(
                    self._sf_url(f"/sobjects/User/{external_id}"),
                    headers=self._headers(token),
                    json=attributes,
                )
                # Salesforce PATCH returns 204 on success
                ok = resp.status_code == 204
                return ConnectorResult(
                    success=ok,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}" if not ok else None,
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        """Salesforce users cannot be deleted; deactivate instead."""
        return await self.disable_user(external_id)

    async def enable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"IsActive": True})

    async def disable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"IsActive": False})

    async def get_user(self, external_id: str) -> ConnectorResult:
        try:
            token = await self._authenticate()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self._sf_url(f"/sobjects/User/{external_id}"),
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
            token = await self._authenticate()
            soql = (
                filter
                or "SELECT Id, Username, Email, FirstName, LastName, IsActive, ProfileId FROM User LIMIT 200"
            )
            # URL-encode the SOQL query
            import urllib.parse
            encoded = urllib.parse.quote(soql)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self._sf_url(f"/query?q={encoded}"),
                    headers=self._headers(token),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return ConnectorResult(
                        success=True,
                        data={
                            "users": data.get("records", []),
                            "total": data.get("totalSize", 0),
                        },
                    )
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Additional Salesforce-specific operations
    # ------------------------------------------------------------------

    async def assign_permission_set(
        self, user_id: str, permission_set_id: str
    ) -> ConnectorResult:
        """Assign a Salesforce Permission Set to a user."""
        try:
            token = await self._authenticate()
            payload = {
                "AssigneeId": user_id,
                "PermissionSetId": permission_set_id,
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._sf_url("/sobjects/PermissionSetAssignment/"),
                    headers=self._headers(token),
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        """Trigger a Salesforce password reset email."""
        try:
            token = await self._authenticate()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._sf_url(f"/sobjects/User/{external_id}/password"),
                    headers=self._headers(token),
                    json={"NewPassword": new_password},
                )
                if resp.status_code in (200, 204):
                    return ConnectorResult(success=True)
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))
