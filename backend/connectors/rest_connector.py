"""
Generic REST Connector for IGA Platform.
Supports bearer, basic, api_key, and OAuth2 authentication with configurable field mappings.
"""
import httpx
import base64
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class RESTConnector(BaseConnector):
    connector_type = "rest"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "").rstrip("/")
        self.auth_type = config.get("auth_type", "bearer")  # bearer, basic, api_key, oauth2
        self.token = self._decrypt_config("token")
        self.username = config.get("username", "")
        self.password = self._decrypt_config("password")
        self.api_key = self._decrypt_config("api_key")
        self.api_key_header = config.get("api_key_header", "X-API-Key")
        self.timeout = int(config.get("timeout", 30))

        # Field mappings — override via config to adapt to any REST API schema
        self.user_path = config.get("user_path", "/users")
        self.username_field = config.get("username_field", "username")
        self.email_field = config.get("email_field", "email")
        self.first_name_field = config.get("first_name_field", "first_name")
        self.last_name_field = config.get("last_name_field", "last_name")
        self.active_field = config.get("active_field", "active")
        self.id_field = config.get("id_field", "id")

        # OAuth2 client credentials (optional)
        self.oauth2_token_url = config.get("oauth2_token_url", "")
        self.oauth2_client_id = config.get("oauth2_client_id", "")
        self.oauth2_client_secret = self._decrypt_config("oauth2_client_secret")
        self._oauth2_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    async def _get_oauth2_token(self) -> str:
        if self._oauth2_token:
            return self._oauth2_token
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.oauth2_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.oauth2_client_id,
                    "client_secret": self.oauth2_client_secret,
                },
            )
            resp.raise_for_status()
            self._oauth2_token = resp.json()["access_token"]
            return self._oauth2_token

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_type == "basic":
            creds = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"
        elif self.auth_type == "api_key":
            headers[self.api_key_header] = self.api_key
        # oauth2 token injected separately via async call
        return headers

    async def _auth_headers(self) -> Dict[str, str]:
        headers = self._get_headers()
        if self.auth_type == "oauth2":
            token = await self._get_oauth2_token()
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # ------------------------------------------------------------------
    # Payload mapping
    # ------------------------------------------------------------------

    def _map_user_to_payload(self, user: UserAccount) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            self.username_field: user.username,
            self.email_field: user.email,
            self.first_name_field: user.first_name,
            self.last_name_field: user.last_name,
            self.active_field: user.is_active,
        }
        if user.attributes:
            # Allow extra fields to pass through
            for k, v in user.attributes.items():
                if k not in payload:
                    payload[k] = v
        return payload

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = await self._auth_headers()
                resp = await client.get(
                    f"{self.base_url}{self.user_path}",
                    headers=headers,
                    params={"limit": 1},
                )
                if resp.status_code in (200, 401, 403):
                    return ConnectorResult(
                        success=resp.status_code == 200,
                        data={"status_code": resp.status_code},
                        error=f"HTTP {resp.status_code}" if resp.status_code != 200 else None,
                    )
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # User lifecycle
    # ------------------------------------------------------------------

    async def create_user(self, user: UserAccount) -> ConnectorResult:
        payload = self._map_user_to_payload(user)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = await self._auth_headers()
                resp = await client.post(
                    f"{self.base_url}{self.user_path}",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return ConnectorResult(
                        success=True,
                        data={
                            "external_id": str(data.get(self.id_field, "")),
                            "user": data,
                        },
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = await self._auth_headers()
                resp = await client.patch(
                    f"{self.base_url}{self.user_path}/{external_id}",
                    headers=headers,
                    json=attributes,
                )
                ok = resp.status_code in (200, 204)
                return ConnectorResult(
                    success=ok,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}" if not ok else None,
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = await self._auth_headers()
                resp = await client.delete(
                    f"{self.base_url}{self.user_path}/{external_id}",
                    headers=headers,
                )
                return ConnectorResult(
                    success=resp.status_code in (200, 204, 404)
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def enable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {self.active_field: True})

    async def disable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {self.active_field: False})

    async def get_user(self, external_id: str) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = await self._auth_headers()
                resp = await client.get(
                    f"{self.base_url}{self.user_path}/{external_id}",
                    headers=headers,
                )
                if resp.status_code == 200:
                    return ConnectorResult(success=True, data=resp.json())
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def list_users(self, filter: str = None) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = await self._auth_headers()
                params: Dict[str, Any] = {}
                if filter:
                    params["filter"] = filter
                resp = await client.get(
                    f"{self.base_url}{self.user_path}",
                    headers=headers,
                    params=params,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Normalise various wrapper formats
                    if isinstance(data, list):
                        users = data
                    else:
                        users = (
                            data.get("data")
                            or data.get("users")
                            or data.get("items")
                            or data.get("results")
                            or []
                        )
                    return ConnectorResult(
                        success=True,
                        data={"users": users, "total": len(users)},
                    )
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        return await self.update_user(external_id, {"password": new_password})
