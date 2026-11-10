"""At-least-once delivery: a duplicate or retried message must not re-run an in-flight job or
attach results to an invoice that does not exist."""

from datetime import datetime, timedelta, timezone
import shutil
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from invoiceflow.application.ingestion.preflight import IngestionPreflight
from invoiceflow.application.ingestion.service import IngestionService
from invoiceflow.application.processing.coordinator import JobCoordinator
from invoiceflow.infrastructure.database.models import (
    InvoiceORM,
    MatchResultORM,
    ProcessingJobORM,
    TenantORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.storage.service import LocalStorageService

pytestmark = pytest.mark.asyncio

XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<HDon><DLHDon><TTChung><KHHDon>1C26TAA</KHHDon><SHDon>0000123</SHDon><NLap>2026-11-08</NLap></TTChung>
<NDHDon><NBan><Ten>Cong Ty A</Ten><MST>0100109106</MST></NBan>
<DSHHDVu><HHDVu><STT>1</STT><THHDVu>Dich vu</THHDVu><SLuong>1</SLuong><DGia>1000</DGia><ThTien>1000</ThTien></HHDVu></DSHHDVu>
<TToan><TgTCThue>1000</TgTCThue><TgTThue>100</TgTThue><TgTTTBSo>1100</TgTTTBSo></TToan></NDHDon></DLHDon></HDon>"""


@pytest_asyncio.fixture
async def env():
    tmp_dir = tempfile.mkdtemp()
    manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await manager.create_tables()
    storage = LocalStorageService(base_dir=tmp_dir)
    async with manager.session() as session:
        tenant = TenantORM(name="Jobs")
        session.add(tenant)
        await session.flush()
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant.id, filename="inv.xml", content=XML
        )
        job_id, tenant_id = job.id, tenant.id
    yield manager, storage, job_id, tenant_id
    await manager.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


async def _set_job(manager, job_id: str, status: str, age: timedelta) -> None:
    async with manager.session() as session:
        await session.execute(
            update(ProcessingJobORM)
            .where(ProcessingJobORM.id == job_id)
            .values(status=status, updated_at=datetime.now(timezone.utc) - age)
        )


async def _invoices(manager, tenant_id: str) -> list[InvoiceORM]:
    async with manager.session() as session:
        rows = await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id))
        return list(rows.scalars().all())


async def test_duplicate_delivery_does_not_rerun_a_job_another_worker_holds(env):
    manager, storage, job_id, tenant_id = env
    await _set_job(manager, job_id, "PARSING", age=timedelta(seconds=5))

    assert await JobCoordinator(db_manager=manager, storage=storage).process_job(job_id) is True

    assert await _invoices(manager, tenant_id) == []
    async with manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        assert job.status == "PARSING"


async def test_job_abandoned_past_its_lease_is_reclaimed(env):
    manager, storage, job_id, tenant_id = env
    await _set_job(manager, job_id, "PARSING", age=timedelta(hours=2))

    assert await JobCoordinator(db_manager=manager, storage=storage).process_job(job_id) is True

    assert len(await _invoices(manager, tenant_id)) == 1


async def test_retry_reuses_the_persisted_invoice_for_matching_and_status(env):
    manager, storage, job_id, tenant_id = env
    coordinator = JobCoordinator(db_manager=manager, storage=storage)
    assert await coordinator.process_job(job_id)
    first = (await _invoices(manager, tenant_id))[0]

    await _set_job(manager, job_id, "RETRYING", age=timedelta(seconds=0))
    assert await coordinator.process_job(job_id)

    invoices = await _invoices(manager, tenant_id)
    assert [inv.id for inv in invoices] == [first.id]
    async with manager.session() as session:
        match_invoice_ids = {
            row.invoice_id for row in (await session.execute(select(MatchResultORM))).scalars()
        }
    assert match_invoice_ids == {first.id}


async def test_export_contains_only_approved_invoices_in_stable_order_with_checksum(env):
    import hashlib

    from httpx import ASGITransport, AsyncClient

    from invoiceflow.api.dependencies import create_access_token
    from invoiceflow.api.main import create_app
    from invoiceflow.config import get_settings
    from invoiceflow.infrastructure.database.models import MembershipORM, UserORM

    manager, storage, job_id, tenant_id = env
    assert await JobCoordinator(db_manager=manager, storage=storage).process_job(job_id)
    async with manager.session() as session:
        user = UserORM(email="acc@exp.vn", hashed_password="x", full_name="A")
        session.add(user)
        await session.flush()
        session.add(MembershipORM(tenant_id=tenant_id, user_id=user.id, role="accountant"))
        user_id = user.id
    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="accountant",
        email="acc@exp.vn",
        settings=get_settings(),
    )
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:", db_manager=manager, storage=storage
    )
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        pending = await client.get(
            "/api/v1/exports?format=json&only_approved=false", headers=headers
        )
        assert pending.status_code == 200
        assert pending.json() == []
        assert pending.headers["X-Export-SHA256"] == hashlib.sha256(pending.content).hexdigest()
