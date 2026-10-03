import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_organization_and_owner(client: AsyncClient):
    """Test successful organization and owner user registration."""
    payload = {
        "email": "cto@innovate.com",
        "password": "SecurePassword123!",
        "full_name": "Chief Architect",
        "org_name": "Innovate Labs",
        "org_slug": "innovate-labs",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "user" in data
    assert "tokens" in data
    assert data["user"]["email"] == "cto@innovate.com"
    assert data["user"]["role"] == "owner"
    assert "access_token" in data["tokens"]
    assert "refresh_token" in data["tokens"]


@pytest.mark.asyncio
async def test_duplicate_registration_fails(client: AsyncClient):
    """Attempting to register with an existing email returns 409 Conflict."""
    payload = {
        "email": "duplicate@test.com",
        "password": "SecurePassword123!",
        "full_name": "Test User",
        "org_name": "Test Org",
    }
    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409


@pytest.mark.asyncio
async def test_login_successful(client: AsyncClient):
    """Test user login returns valid access and refresh tokens."""
    # Register first
    reg = {
        "email": "user@login.com",
        "password": "ValidPassword123!",
        "full_name": "Login User",
        "org_name": "Login Org",
    }
    await client.post("/api/v1/auth/register", json=reg)

    # Login
    login_payload = {"email": "user@login.com", "password": "ValidPassword123!"}
    response = await client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tokens"]["access_token"] is not None


@pytest.mark.asyncio
async def test_login_bad_password_fails(client: AsyncClient):
    """Attempting to log in with an incorrect password returns 401."""
    reg = {
        "email": "user2@login.com",
        "password": "ValidPassword123!",
        "full_name": "Login User 2",
        "org_name": "Login Org 2",
    }
    await client.post("/api/v1/auth/register", json=reg)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user2@login.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_flow(client: AsyncClient):
    """Test obtaining a new access token via refresh token."""
    reg = {
        "email": "refresh@test.com",
        "password": "ValidPassword123!",
        "full_name": "Refresh User",
        "org_name": "Refresh Org",
    }
    reg_res = await client.post("/api/v1/auth/register", json=reg)
    refresh_token = reg_res.json()["tokens"]["refresh_token"]

    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_rbac_member_cannot_access_admin_routes(client: AsyncClient, seed_two_tenants):
    """Enforce that standard members receive 403 Forbidden on admin endpoints."""
    tenant_a, _ = seed_two_tenants

    # Member hits admin usage -> 403
    res_member = await client.get("/api/v1/admin/usage", headers=tenant_a.member_headers)
    assert res_member.status_code == 403

    # Owner hits admin usage -> 200 OK
    res_owner = await client.get("/api/v1/admin/usage", headers=tenant_a.owner_headers)
    assert res_owner.status_code == 200


@pytest.mark.asyncio
async def test_get_current_user_profile(client: AsyncClient, seed_two_tenants):
    """Test GET /auth/me returns profile for authenticated user."""
    tenant_a, _ = seed_two_tenants
    res = await client.get("/api/v1/auth/me", headers=tenant_a.owner_headers)
    assert res.status_code == 200
    assert res.json()["email"] == tenant_a.owner.email


@pytest.mark.asyncio
async def test_delete_member_flow(client: AsyncClient, seed_two_tenants):
    """Test owner can delete a member, members cannot delete, and self-delete is rejected."""
    tenant_a, tenant_b = seed_two_tenants

    # 1. Standard member cannot call delete member endpoint (403 Forbidden)
    res_member = await client.delete(
        f"/api/v1/admin/members/{tenant_a.member.id}", headers=tenant_a.member_headers
    )
    assert res_member.status_code == 403

    # 2. Owner cannot delete their own account (400 Bad Request)
    res_self = await client.delete(
        f"/api/v1/admin/members/{tenant_a.owner.id}", headers=tenant_a.owner_headers
    )
    assert res_self.status_code == 400

    # 3. Owner cannot delete a member of another tenant (404 Not Found)
    res_cross = await client.delete(
        f"/api/v1/admin/members/{tenant_b.member.id}", headers=tenant_a.owner_headers
    )
    assert res_cross.status_code == 404

    # 4. Owner successfully deletes member of their own tenant (204 No Content)
    res_delete = await client.delete(
        f"/api/v1/admin/members/{tenant_a.member.id}", headers=tenant_a.owner_headers
    )
    assert res_delete.status_code == 204

    # 5. Deleted member no longer appears in members list
    res_list = await client.get("/api/v1/admin/members", headers=tenant_a.owner_headers)
    assert res_list.status_code == 200
    member_ids = [m["id"] for m in res_list.json()]
    assert str(tenant_a.member.id) not in member_ids
