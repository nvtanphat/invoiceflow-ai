import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from invoiceflow.api.dependencies import create_access_token
from invoiceflow.api.main import create_app
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.models import MembershipORM, TenantORM, UserORM
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.security.password import hash_password, verify_password
from invoiceflow.infrastructure.storage.exporter import sanitize_csv_cell


def test_csv_formula_injection_escaping():
    assert sanitize_csv_cell("Normal Supplier") == "Normal Supplier"
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_csv_cell("-5+2") == "'-5+2"


def test_argon2_password_hashing():
    pw = "SuperSecurePassword#2026"
    hashed = hash_password(pw)
    assert hashed.startswith("$argon2id$")
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password(pw, "corrupted_hash") is False
    assert verify_password("", hashed) is False


@pytest.mark.asyncio
async def test_auth_inactive_user_and_revoked_membership():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    active_user_id = str(uuid.uuid4())
    inactive_user_id = str(uuid.uuid4())
    stranger_user_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="Security Test Tenant")
        u_active = UserORM(
            id=active_user_id,
            email="active@security.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Active User",
            is_active=True,
        )
        u_inactive = UserORM(
            id=inactive_user_id,
            email="inactive@security.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Inactive User",
            is_active=False,
        )
        u_stranger = UserORM(
            id=stranger_user_id,
            email="stranger@security.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Stranger User",
            is_active=True,
        )
        m = MembershipORM(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=active_user_id,
            role="reviewer",
        )
        session.add_all([t, u_active, u_inactive, u_stranger, m])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inactive user cannot login
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@security.vn", "password": "Pass123!"},
        )
        assert login_res.status_code == 401

        # Token generated for inactive user is rejected by dependencies
        inactive_token = create_access_token(
            user_id=inactive_user_id,
            tenant_id=tenant_id,
            role="reviewer",
            email="inactive@security.vn",
            settings=settings,
        )
        res = await client.get(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {inactive_token}"},
        )
        assert res.status_code == 401
        assert "inactive" in res.json()["detail"].lower()

        # Token generated for user without tenant membership is rejected by dependencies
        stranger_token = create_access_token(
            user_id=stranger_user_id,
            tenant_id=tenant_id,
            role="reviewer",
            email="stranger@security.vn",
            settings=settings,
        )
        res = await client.get(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
        assert res.status_code == 403
        assert "revoked" in res.json()["detail"].lower() or "not found" in res.json()["detail"].lower()
