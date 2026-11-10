import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_endpoints():
    from invoiceflow.api.main import create_app

    app = create_app(database_url="sqlite+aiosqlite:///:memory:")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        live_res = await client.get("/health/live")
        assert live_res.status_code == 200
        assert live_res.json()["status"] == "alive"

        ready_res = await client.get("/health/ready")
        assert ready_res.status_code == 200
        assert ready_res.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_auth_login_and_protected_route():
    from invoiceflow.api.main import create_app
    from invoiceflow.infrastructure.database.session import DatabaseSessionManager
    from invoiceflow.infrastructure.database.models import TenantORM, UserORM, MembershipORM
    from invoiceflow.infrastructure.security.password import hash_password
    import uuid

    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    pwd_hash = hash_password("password123")

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="Tenant Demo")
        u = UserORM(
            id=user_id,
            email="accountant@example.com",
            hashed_password=pwd_hash,
            full_name="Nguyễn Văn A",
            is_active=True,
        )
        m = MembershipORM(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            role="accountant",
        )
        session.add_all([t, u, m])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid credentials -> 401
        bad_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "accountant@example.com", "password": "wrongpassword"},
        )
        assert bad_login.status_code == 401

        # Valid login -> 200 + token
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "accountant@example.com", "password": "password123"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        assert token is not None

        # Email addresses are case-insensitive; provisioning stores them lowercased.
        mixed_case = await client.post(
            "/api/v1/auth/login",
            json={"email": "Accountant@Example.com", "password": "password123"},
        )
        assert mixed_case.status_code == 200

        # Access documents endpoint with Bearer token
        headers = {"Authorization": f"Bearer {token}"}
        docs_res = await client.get("/api/v1/documents", headers=headers)
        assert docs_res.status_code == 200

    await db_manager.close()
