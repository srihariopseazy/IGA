"""Security tests for the IGA platform."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_sql_injection_login(client: AsyncClient) -> None:
    payloads = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "admin'--",
        "' UNION SELECT * FROM users --",
    ]
    for payload in payloads:
        resp = await client.post("/api/v1/auth/login", json={
            "email": payload,
            "password": payload,
        })
        assert resp.status_code in (400, 401, 422), f"SQL injection not blocked: {payload}"


@pytest.mark.asyncio
async def test_xss_in_user_fields(client: AsyncClient, admin_auth_headers: dict) -> None:
    xss_payloads = [
        "<script>alert('xss')</script>",
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
    ]
    for payload in xss_payloads:
        resp = await client.post("/api/v1/users", headers=admin_auth_headers, json={
            "email": f"test_{hash(payload) % 10000}@example.com",
            "first_name": payload,
            "last_name": "Test",
            "password": "SecurePass@123",
            "username": f"user_{hash(payload) % 10000}",
        })
        if resp.status_code in (200, 201):
            response_text = resp.text
            assert "<script>" not in response_text
            assert "javascript:" not in response_text


@pytest.mark.asyncio
async def test_rate_limiting_auth(client: AsyncClient) -> None:
    for i in range(15):
        await client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "wrong_password",
        })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "wrong_password",
    })
    assert resp.status_code in (429, 401)


@pytest.mark.asyncio
async def test_jwt_tampering(client: AsyncClient, auth_headers: dict) -> None:
    token = auth_headers["Authorization"].split(" ")[1]
    parts = token.split(".")
    if len(parts) == 3:
        tampered = parts[0] + "." + parts[1] + "TAMPERED." + parts[2]
        resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unauthorized_tenant_access(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.get(
        "/api/v1/users",
        headers={**auth_headers, "X-Tenant-ID": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code in (400, 401, 403, 404)


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    headers = dict(resp.headers)
    assert "x-content-type-options" in headers or "X-Content-Type-Options" in headers
    assert "x-frame-options" in headers or "X-Frame-Options" in headers


@pytest.mark.asyncio
async def test_no_sensitive_data_in_error(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "wrongpass",
    })
    body = resp.text.lower()
    assert "password" not in body
    assert "secret" not in body
    assert "traceback" not in body


@pytest.mark.asyncio
async def test_password_complexity(client: AsyncClient, admin_auth_headers: dict) -> None:
    weak_passwords = ["123456", "password", "abc", "aaaaaa"]
    for pwd in weak_passwords:
        resp = await client.post("/api/v1/users", headers=admin_auth_headers, json={
            "email": f"weakpwd_{hash(pwd) % 10000}@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": pwd,
            "username": f"weakpwd_{hash(pwd) % 10000}",
        })
        assert resp.status_code in (400, 422), f"Weak password accepted: {pwd}"


@pytest.mark.asyncio
async def test_idor_protection(client: AsyncClient, auth_headers: dict) -> None:
    import uuid
    random_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/users/{random_id}", headers=auth_headers)
    assert resp.status_code in (403, 404)
