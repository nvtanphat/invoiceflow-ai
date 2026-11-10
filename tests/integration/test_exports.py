"""Accounting export is a one-way hand-off: an invoice can be posted to the ERP only once."""

from decimal import Decimal
import hashlib
import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from invoiceflow.api.dependencies import create_access_token
from invoiceflow.api.main import create_app
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    InvoiceORM,
    MembershipORM,
    TenantORM,
    UserORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api():
    manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await manager.create_tables()
    async with manager.session() as session:
        tenant = TenantORM(name="Export")
        user = UserORM(email="acc@export.vn", hashed_password="x", full_name="Acc")
        session.add_all([tenant, user])
        await session.flush()
        session.add(MembershipORM(tenant_id=tenant.id, user_id=user.id, role="accountant"))
        for number, status in (
            ("0000003", "APPROVED"),
            ("0000001", "APPROVED"),
            ("0000002", "READY_FOR_REVIEW"),
        ):
            session.add(
                InvoiceORM(
                    tenant_id=tenant.id,
                    document_id=str(uuid.uuid4()),
                    status=status,
                    invoice_number=number,
                    supplier_tax_id="0100109106",
                    amount_payable=Decimal("1100.0000"),
                    subtotal=Decimal("1000.0000"),
                    tax_total=Decimal("100.0000"),
                )
            )
        tenant_id, user_id = tenant.id, user.id
    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="accountant",
        email="acc@export.vn",
        settings=get_settings(),
    )
    app = create_app(database_url="sqlite+aiosqlite:///:memory:", db_manager=manager)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, {"Authorization": f"Bearer {token}"}, manager, tenant_id
    await manager.close()


async def test_download_is_read_only_ordered_and_checksummed(api):
    client, headers, manager, tenant_id = api

    res = await client.get(
        "/api/v1/exports/invoices?format=json&only_approved=false", headers=headers
    )

    rows = res.json()
    assert [r["invoice_number"] for r in rows] == ["0000001", "0000003"]
    assert res.headers["X-Export-SHA256"] == hashlib.sha256(res.content).hexdigest()
    async with manager.session() as session:
        statuses = {
            inv.status
            for inv in (
                await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id))
            ).scalars()
        }
    assert "EXPORTED" not in statuses


async def test_posting_an_export_marks_invoices_exported_so_they_cannot_be_posted_twice(api):
    client, headers, manager, tenant_id = api

    first = await client.post("/api/v1/exports", headers=headers, json={"format": "json"})
    second = await client.post("/api/v1/exports", headers=headers, json={"format": "json"})

    assert [r["invoice_number"] for r in first.json()] == ["0000001", "0000003"]
    assert all(r["status"] == "EXPORTED" for r in first.json())
    assert second.json() == []
    async with manager.session() as session:
        invoices = (
            (await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        audits = (
            (
                await session.execute(
                    select(AuditLogORM).where(AuditLogORM.action == "INVOICES_EXPORTED")
                )
            )
            .scalars()
            .all()
        )
    assert sorted(inv.status for inv in invoices) == ["EXPORTED", "EXPORTED", "READY_FOR_REVIEW"]
    assert len(audits) == 1
    details = json.loads(audits[0].details_json)
    assert len(details["invoice_ids"]) == 2
    assert details["sha256"] == first.headers["X-Export-SHA256"]
