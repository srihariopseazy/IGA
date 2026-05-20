from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import httpx

from backend.config import settings


class OPAClient:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or settings.OPA_URL).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def evaluate(
        self,
        policy_path: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        client = await self._get_client()
        url = f"{self.base_url}/v1/data/{policy_path.lstrip('/')}"
        payload = {"input": input_data}
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("result", {})
        except httpx.HTTPError:
            return {}

    async def check_access(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        resource: str,
        action: str,
        context: Optional[dict] = None,
    ) -> bool:
        input_data = {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "resource": resource,
            "action": action,
            "context": context or {},
        }
        result = await self.evaluate("iga/authz/allow", input_data)
        return bool(result)

    async def evaluate_sod(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        entitlements: list[str],
    ) -> list[dict]:
        input_data = {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "entitlements": entitlements,
        }
        result = await self.evaluate("iga/sod/violations", input_data)
        return result if isinstance(result, list) else []

    async def evaluate_risk_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        risk_score: float,
        action: str,
    ) -> dict[str, Any]:
        input_data = {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "risk_score": risk_score,
            "action": action,
        }
        result = await self.evaluate("iga/risk/decision", input_data)
        return result if isinstance(result, dict) else {"allow": True, "require_mfa": False}

    async def upload_policy(self, policy_path: str, policy_rego: str) -> bool:
        client = await self._get_client()
        url = f"{self.base_url}/v1/policies/{policy_path.lstrip('/')}"
        try:
            response = await client.put(
                url,
                content=policy_rego.encode(),
                headers={"Content-Type": "text/plain"},
            )
            return response.status_code in (200, 201)
        except httpx.HTTPError:
            return False


_opa_client: Optional[OPAClient] = None


def get_opa_client() -> OPAClient:
    global _opa_client
    if _opa_client is None:
        _opa_client = OPAClient()
    return _opa_client
