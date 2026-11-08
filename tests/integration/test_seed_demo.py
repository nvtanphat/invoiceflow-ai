import pytest
from sqlalchemy import select
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.database.models import (
    TenantORM,
    UserORM,
    PurchaseOrderORM,
    InvoiceORM,
)


@pytest.mark.asyncio
async def test_seed_demo_script():
    from scripts.seed_demo import seed_all

    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        await seed_all(db_manager)

        async with db_manager.session() as session:
            # Check tenants
            tenants = (await session.execute(select(TenantORM))).scalars().all()
            assert len(tenants) >= 2

            # Check users
            users = (await session.execute(select(UserORM))).scalars().all()
            assert len(users) >= 4
            emails = {u.email for u in users}
            assert "admin@invoiceflow.vn" in emails
            assert "accountant@invoiceflow.vn" in emails

            # Check purchase orders
            pos = (await session.execute(select(PurchaseOrderORM))).scalars().all()
            assert len(pos) >= 2

            # Check invoices
            invoices = (await session.execute(select(InvoiceORM))).scalars().all()
            assert len(invoices) >= 2
    finally:
        await db_manager.close()
