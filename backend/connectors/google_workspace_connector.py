"""
Google Workspace Connector for IGA Platform.
Uses the Admin SDK Directory REST API with service account JWT (domain-wide delegation).
Requires PyJWT >= 2.x: pip install PyJWT cryptography
"""
import httpx
import json
import time
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class GoogleWorkspaceConnector(BaseConnector):
    connector_type = "google_workspace"

    ADMIN_API = "https://admin.googleapis.com/admin/directory/v1"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPE = (
        "https://www.googleapis.com/auth/admin.directory.user "
        "https://www.googleapis.com/auth/admin.directory.group"
    )

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        key_json = self._decrypt_config("service_account_key")
        try:
            self.service_account: Dict[str, Any] = json.loads(key_json) if key_json else {}
        except (json.JSONDecodeError, Exception):
            self.service_account = {}
        self.admin_email = config.get("admin_email", "")
        self.domain = config.get("domain", "")
        self.timeout = int(config.get("timeout", 30))
        self._cached_token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------
    # Token management (JWT bearer grant)
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        if self._cached_token and time.time() < self._token_expiry - 60:
            return self._cached_token

        if not self.service_account:
            raise ValueError("service_account_key is not configured or invalid JSON")

        try:
            import jwt as pyjwt  # PyJWT
        except ImportError:
            raise ImportError("PyJWT is required: pip install PyJWT cryptography")

        now = int(time.time())
        claims = {
            "iss": self.service_account.get("client_email", ""),
            "sub": self.admin_email,
            "scope": self.SCOPE,
            "aud": self.TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        private_key = self.service_account.get("private_key", "")
        assertion = pyjwt.encode(claims, private_key, algorithm="RS256")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            resp.raise_for_status()
            token_data = resp.json()
            self._cached_token = token_data["access_token"]
            self._token_expiry = time.time() + token_data.get("expires_in", 3600)
            return self._cached_token

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
                    f"{self.ADMIN_API}/users",
                    headers=self._headers(token),
                    params={"domain": self.domain, "maxResults": 1},
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
            payload: Dict[str, Any] = {
                "primaryEmail": user.email,
                "name": {
                    "givenName": user.first_name,
                    "familyName": user.last_name,
                    "fullName": f"{user.first_name} {user.last_name}",
                },
                "password": attrs.get("temp_password", "TempPass123!@#"),
                "changePasswordAtNextLogin": True,
                "suspended": not user.is_active,
            }
            if attrs.get("org_unit_path"):
                payload["orgUnitPath"] = attrs["org_unit_path"]
            if attrs.get("recovery_email"):
                payload["recoveryEmail"] = attrs["recovery_email"]

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.ADMIN_API}/users",
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
        """PUT update — Google Directory API uses PUT for full or partial updates via userKey."""
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.put(
                    f"{self.ADMIN_API}/users/{external_id}",
                    headers=self._headers(token),
                    json=attributes,
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        """Suspend the user (Google recommends suspension over hard delete for IGA)."""
        return await self.disable_user(external_id)

    async def enable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"suspended": False})

    async def disable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"suspended": True})

    async def get_user(self, external_id: str) -> ConnectorResult:
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.ADMIN_API}/users/{external_id}",
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
            all_users: List[Dict[str, Any]] = []
            params: Dict[str, Any] = {
                "domain": self.domain,
                "maxResults": 200,
            }
            if filter:
                params["query"] = filter

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                while True:
                    resp = await client.get(
                        f"{self.ADMIN_API}/users",
                        headers=self._headers(token),
                        params=params,
                    )
                    if resp.status_code != 200:
                        return ConnectorResult(
                            success=False, error=f"HTTP {resp.status_code}"
                        )
                    data = resp.json()
                    all_users.extend(data.get("users", []))
                    next_page = data.get("nextPageToken")
                    if not next_page:
                        break
                    params["pageToken"] = next_page
                    params.pop("domain", None)  # nextPageToken supersedes domain

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
            payload = {"email": user_id, "role": "MEMBER"}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.ADMIN_API}/groups/{group_id}/members",
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

    async def remove_from_group(self, user_id: str, group_id: str) -> ConnectorResult:
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.delete(
                    f"{self.ADMIN_API}/groups/{group_id}/members/{user_id}",
                    headers=self._headers(token),
                )
                return ConnectorResult(
                    success=resp.status_code in (200, 204, 404)
                )
        except Exception as exc:
            return ConnectorResult(success=False, error=str(exc))

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        return await self.update_user(
            external_id,
            {
                "password": new_password,
                "changePasswordAtNextLogin": True,
            },
        )
