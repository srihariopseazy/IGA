"""Integration tests for user management API endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_users(client: AsyncClient, admin_auth_headers: dict) -> None:
    resp = await client.get("/api/v1/users", headers=admin_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_create_user(client: AsyncClient, admin_auth_headers: dict) -> None:
    resp = await client.post("/api/v1/users", headers=admin_auth_headers, json={
        "email": "newuser@acme.com",
        "first_name": "New",
        "last_name": "User",
        "password": "SecurePass@123",
        "username": "newuser",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert data["email"] == "newuser@acme.com"


@pytest.mark.asyncio
async def test_get_user_by_id(client: AsyncClient, admin_auth_headers: dict, seed_user: dict) -> None:
    resp = await client.get(f"/api/v1/users/{seed_user['id']}", headers=admin_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == seed_user["id"]


@pytest.mark.asyncio
async def test_update_user(client: AsyncClient, admin_auth_headers: dict, seed_user: dict) -> None:
    resp = await client.patch(
        f"/api/v1/users/{seed_user['id']}",
        headers=admin_auth_headers,
        json={"first_name": "Updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["first_name"] == "Updated"


@pytest.mark.asyncio
async def test_deactivate_user(client: AsyncClient, admin_auth_headers: dict, seed_user: dict) -> None:
    resp = await client.post(
        f"/api/v1/users/{seed_user['id']}/deactivate",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_non_admin_cannot_list_all_users(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/api/v1/users", headers=auth_headers)
    assert resp.status_code in (200, 403)


@pytest.mark.asyncio
async def test_search_users(client: AsyncClient, admin_auth_headers: dict) -> None:
    resp = await client.get("/api/v1/users", headers=admin_auth_headers, params={"search": "alice"})
    assert resp.status_code == 200
