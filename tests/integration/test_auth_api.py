"""Integration tests for authentication API endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, seed_user: dict) -> None:
    resp = await client.post("/api/v1/auth/login", json={
        "email": seed_user["email"],
        "password": seed_user["password"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data["data"]
    assert "refresh_token" in data["data"]
    assert data["data"]["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, seed_user: dict) -> None:
    resp = await client.post("/api/v1/auth/login", json={
        "email": seed_user["email"],
        "password": "wrong_password",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@nowhere.com",
        "password": "password",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh(client: AsyncClient, seed_user: dict) -> None:
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": seed_user["email"],
        "password": seed_user["password"],
    })
    refresh_token = login_resp.json()["data"]["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()["data"]


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.post("/api/v1/auth/logout", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/api/v1/users/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "email" in data
    assert "id" in data


@pytest.mark.asyncio
async def test_access_protected_without_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_access_protected_with_invalid_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert resp.status_code == 401
