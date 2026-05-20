"""
ServiceNow Connector for IGA Platform.
Uses the ServiceNow Table API with Basic Authentication.
Manages users (sys_user), incidents, and change requests.
"""
import httpx
import base64
from typing import Dict, Any, List, Optional

from backend.connectors.base import BaseConnector, ConnectorResult, UserAccount


class ServiceNowConnector(BaseConnector):
    connector_type = "servicenow"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.instance_url = config.get("instance_url", "").rstrip("/")
        self.username = config.get("username", "")
        self.password = self._decrypt_config("password")
        self.timeout = int(config.get("timeout", 30))
        self.api_version = config.get("api_version", "v1")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_headers(self) -> Dict[str, str]:
        creds = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _table_url(self, table: str) -> str:
        return f"{self.instance_url}/api/now/{self.api_version}/table/{table}"

    def _record_url(self, table: str, sys_id: str) -> str:
        return f"{self._table_url(table)}/{sys_id}"

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    self._table_url("sys_user"),
                    headers=self._get_headers(),
                    params={"sysparm_limit": 1, "sysparm_fields": "sys_id"},
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
        attrs = user.attributes or {}
        payload: Dict[str, Any] = {
            "user_name": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "active": str(user.is_active).lower(),
            "user_password": attrs.get("temp_password", "TempPass123!@#"),
            "title": attrs.get("title", ""),
            "department": attrs.get("department", ""),
            "manager": attrs.get("manager_sys_id", ""),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    self._table_url("sys_user"),
                    headers=self._get_headers(),
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json().get("result", {})
                    return ConnectorResult(
                        success=True,
                        data={"external_id": data.get("sys_id"), "user": data},
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
                resp = await client.patch(
                    self._record_url("sys_user", external_id),
                    headers=self._get_headers(),
                    json=attributes,
                )
                if resp.status_code == 200:
                    return ConnectorResult(
                        success=True, data=resp.json().get("result", {})
                    )
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def delete_user(self, external_id: str) -> ConnectorResult:
        """ServiceNow users should be deactivated, not deleted."""
        return await self.disable_user(external_id)

    async def enable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"active": "true"})

    async def disable_user(self, external_id: str) -> ConnectorResult:
        return await self.update_user(external_id, {"active": "false"})

    async def get_user(self, external_id: str) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    self._record_url("sys_user", external_id),
                    headers=self._get_headers(),
                )
                if resp.status_code == 200:
                    return ConnectorResult(
                        success=True, data=resp.json().get("result", {})
                    )
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def list_users(self, filter: str = None) -> ConnectorResult:
        params: Dict[str, Any] = {
            "sysparm_limit": 200,
            "sysparm_fields": (
                "sys_id,user_name,first_name,last_name,email,active,department,title"
            ),
        }
        if filter:
            params["sysparm_query"] = filter

        all_users: List[Dict[str, Any]] = []
        offset = 0
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                try:
                    params["sysparm_offset"] = offset
                    resp = await client.get(
                        self._table_url("sys_user"),
                        headers=self._get_headers(),
                        params=params,
                    )
                    if resp.status_code != 200:
                        return ConnectorResult(
                            success=False, error=f"HTTP {resp.status_code}"
                        )
                    data = resp.json().get("result", [])
                    if not data:
                        break
                    all_users.extend(data)
                    if len(data) < 200:
                        break
                    offset += 200
                except Exception as exc:
                    return ConnectorResult(success=False, error=str(exc))

        return ConnectorResult(
            success=True,
            data={"users": all_users, "total": len(all_users)},
        )

    # ------------------------------------------------------------------
    # Incident management
    # ------------------------------------------------------------------

    async def create_incident(
        self,
        short_description: str,
        description: str = "",
        caller_id: str = "",
        urgency: int = 3,
        impact: int = 3,
        category: str = "access",
        assignment_group: str = "",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> ConnectorResult:
        """Create a ServiceNow Incident record."""
        payload: Dict[str, Any] = {
            "short_description": short_description,
            "description": description,
            "caller_id": caller_id,
            "urgency": urgency,
            "impact": impact,
            "category": category,
        }
        if assignment_group:
            payload["assignment_group"] = assignment_group
        if extra_fields:
            payload.update(extra_fields)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    self._table_url("incident"),
                    headers=self._get_headers(),
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json().get("result", {})
                    return ConnectorResult(
                        success=True,
                        data={
                            "sys_id": data.get("sys_id"),
                            "number": data.get("number"),
                            "incident": data,
                        },
                    )
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Change request management
    # ------------------------------------------------------------------

    async def create_change_request(
        self,
        short_description: str,
        description: str = "",
        type: str = "normal",
        risk: str = "moderate",
        requested_by: str = "",
        assignment_group: str = "",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> ConnectorResult:
        """Create a ServiceNow Change Request record."""
        payload: Dict[str, Any] = {
            "short_description": short_description,
            "description": description,
            "type": type,
            "risk": risk,
        }
        if requested_by:
            payload["requested_by"] = requested_by
        if assignment_group:
            payload["assignment_group"] = assignment_group
        if extra_fields:
            payload.update(extra_fields)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    self._table_url("change_request"),
                    headers=self._get_headers(),
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json().get("result", {})
                    return ConnectorResult(
                        success=True,
                        data={
                            "sys_id": data.get("sys_id"),
                            "number": data.get("number"),
                            "change_request": data,
                        },
                    )
                return ConnectorResult(
                    success=False,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def get_incident(self, sys_id: str) -> ConnectorResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    self._record_url("incident", sys_id),
                    headers=self._get_headers(),
                )
                if resp.status_code == 200:
                    return ConnectorResult(
                        success=True, data=resp.json().get("result", {})
                    )
                return ConnectorResult(
                    success=False, error=f"HTTP {resp.status_code}"
                )
            except Exception as exc:
                return ConnectorResult(success=False, error=str(exc))

    async def resolve_incident(
        self, sys_id: str, resolution_notes: str, resolution_code: str = "Solved (Permanently)"
    ) -> ConnectorResult:
        """Close a ServiceNow incident."""
        return await self.update_user(
            sys_id,
            {
                "state": "6",
                "close_code": resolution_code,
                "close_notes": resolution_notes,
            },
        )

    async def reset_password(self, external_id: str, new_password: str) -> ConnectorResult:
        return await self.update_user(external_id, {"user_password": new_password})
