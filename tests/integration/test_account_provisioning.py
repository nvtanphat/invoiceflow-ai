"""First-run provisioning: an operator must be able to create a tenant and its users."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select

from invoiceflow import admin_cli
from invoiceflow.application.accounts.provisioning import (
    ProvisioningError,
    provision_user,
)
from invoiceflow.infrastructure.database.models import MembershipORM, TenantORM, UserORM
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.security.password import verify_password

pytestmark = pytest.mark.asyncio
STRONG = "Correct-Horse-42!"


@pytest_asyncio.fixture
async def db_manager():
    manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await manager.create_tables()
    yield manager
    await manager.close()


async def test_creates_tenant_user_and_membership_with_hashed_password(db_manager):
    async with db_manager.session() as session:
        result = await provision_user(
            session,
            email="Admin@Example.vn",
            full_name="Quản trị",
            password=STRONG,
            role="admin",
            tenant_name="Công ty A",
        )

    async with db_manager.session() as session:
        user = (await session.execute(select(UserORM))).scalar_one()
        membership = (await session.execute(select(MembershipORM))).scalar_one()
        tenant = await session.get(TenantORM, result.tenant_id)

    assert user.email == "admin@example.vn"
    assert user.hashed_password != STRONG
    assert verify_password(STRONG, user.hashed_password)
    assert tenant is not None and tenant.name == "Công ty A"
    assert (membership.tenant_id, membership.user_id, membership.role) == (
        result.tenant_id,
        user.id,
        "admin",
    )


async def test_adds_user_to_existing_tenant(db_manager):
    async with db_manager.session() as session:
        first = await provision_user(
            session,
            email="admin@a.vn",
            full_name="A",
            password=STRONG,
            role="admin",
            tenant_name="A",
        )
    async with db_manager.session() as session:
        second = await provision_user(
            session,
            email="reviewer@a.vn",
            full_name="R",
            password=STRONG,
            role="reviewer",
            tenant_id=first.tenant_id,
        )
    assert second.tenant_id == first.tenant_id


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"role": "superuser"}, "role"),
        ({"password": "short"}, "password"),
        ({"tenant_id": "missing-tenant", "tenant_name": None}, "tenant"),
        ({"tenant_name": None}, "tenant"),
    ],
)
async def test_rejects_invalid_requests(db_manager, overrides, message):
    request = {
        "email": "x@a.vn",
        "full_name": "X",
        "password": STRONG,
        "role": "admin",
        "tenant_name": "A",
    } | overrides
    async with db_manager.session() as session:
        with pytest.raises(ProvisioningError, match=message):
            await provision_user(session, **request)


async def test_rejects_duplicate_email(db_manager):
    request = {
        "email": "dup@a.vn",
        "full_name": "D",
        "password": STRONG,
        "role": "admin",
        "tenant_name": "A",
    }
    async with db_manager.session() as session:
        await provision_user(session, **request)
    async with db_manager.session() as session:
        with pytest.raises(ProvisioningError, match="exists"):
            await provision_user(session, **(request | {"email": "DUP@a.vn"}))


async def test_cli_creates_user_with_password_from_environment(tmp_path, monkeypatch, capsys):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'cli.db').as_posix()}"
    manager = DatabaseSessionManager(database_url=url, echo=False)
    await manager.create_tables()
    await manager.close()
    monkeypatch.setenv(admin_cli.PASSWORD_ENV, STRONG)

    argv = ["create-user", "--email", "ops@a.vn", "--full-name", "Ops", "--role", "admin"]
    argv += ["--tenant-name", "A", "--database-url", url]
    # asyncio.run cannot nest inside the test's loop, so the CLI runs in a worker thread.
    exit_code = await asyncio.to_thread(admin_cli.main, argv)

    assert exit_code == 0
    assert "ops@a.vn" in capsys.readouterr().out
    manager = DatabaseSessionManager(database_url=url, echo=False)
    async with manager.session() as session:
        user = (await session.execute(select(UserORM))).scalar_one()
    await manager.close()
    assert verify_password(STRONG, user.hashed_password)
