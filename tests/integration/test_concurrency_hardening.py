import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import shutil
import tempfile
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, update

from invoiceflow.api.dependencies import create_access_token
from invoiceflow.api.main import create_app
from invoiceflow.application.ingestion.preflight import IngestionPreflight
from invoiceflow.application.ingestion.service import IngestionService
from invoiceflow.application.processing.coordinator import JobCoordinator
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    InvoiceORM,
    MatchResultORM,
    MembershipORM,
    ProcessingJobORM,
    TenantORM,
    UserORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.storage.service import LocalStorageService

pytestmark = pytest.mark.asyncio

XML_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<HDon><DLHDon><TTChung><KHHDon>1C26TCC</KHHDon><SHDon>0008888</SHDon><NLap>2026-11-10</NLap></TTChung>
<NDHDon><NBan><Ten>Cong Ty Concurrency</Ten><MST>0100109106</MST></NBan>
<DSHHDVu><HHDVu><STT>1</STT><THHDVu>Dich vu kiem thu</THHDVu><SLuong>1</SLuong><DGia>500000</DGia><ThTien>500000</ThTien></HHDVu></DSHHDVu>
<TToan><TgTCThue>500000</TgTCThue><TgTThue>50000</TgTThue><TgTTTBSo>550000</TgTTTBSo></TToan></NDHDon></DLHDon></HDon>"""


async def _create_test_document(session, tenant_id: str, name: str = "doc.pdf") -> DocumentORM:
    doc = DocumentORM(
        tenant_id=tenant_id,
        filename=name,
        mime_type="application/pdf",
        file_size_bytes=1024,
        sha256=hashlib.sha256(f"{tenant_id}-{uuid.uuid4()}".encode()).hexdigest(),
        storage_uri=f"local://data/{uuid.uuid4()}.pdf",
        status="RECEIVED",
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest_asyncio.fixture
async def pg_env():
    settings = get_settings()
    if "postgresql" not in settings.DATABASE_URL:
        pytest.skip("Phase 3 concurrency tests require real PostgreSQL.")

    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(
        database_url=settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
    )
    storage = LocalStorageService(base_dir=tmp_dir)

    prefix = f"cc-{uuid.uuid4().hex[:6]}"
    async with db_manager.session() as session:
        tenant = TenantORM(name=f"Tenant {prefix}")
        user = UserORM(
            email=f"reviewer_{prefix}@test.vn",
            hashed_password="hash",
            full_name="Reviewer CC",
            is_active=True,
        )
        session.add_all([tenant, user])
        await session.flush()

        membership = MembershipORM(tenant_id=tenant.id, user_id=user.id, role="admin")
        session.add(membership)
        await session.flush()

        tenant_id = tenant.id
        user_id = user.id

    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="admin",
        email=f"reviewer_{prefix}@test.vn",
        settings=settings,
    )
    auth_headers = {"Authorization": f"Bearer {token}"}
    app = create_app(database_url=settings.DATABASE_URL, db_manager=db_manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "db_manager": db_manager,
            "storage": storage,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "client": client,
            "headers": auth_headers,
            "prefix": prefix,
        }

    await db_manager.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


async def test_3_1_concurrent_worker_claim_single_winner(pg_env):
    """3.1: Two workers concurrently claim the exact same job on PostgreSQL.
    Atomic compare-and-swap guarantees only ONE worker wins the claim."""
    db_manager = pg_env["db_manager"]
    storage = pg_env["storage"]
    tenant_id = pg_env["tenant_id"]

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="concurrent_test.xml", content=XML_CONTENT
        )
        job_id = job.id

    coordinator1 = JobCoordinator(db_manager=db_manager, storage=storage)
    coordinator2 = JobCoordinator(db_manager=db_manager, storage=storage)

    # Launch both workers concurrently
    r1, r2 = await asyncio.gather(
        coordinator1.process_job(job_id),
        coordinator2.process_job(job_id),
        return_exceptions=True,
    )

    assert not isinstance(r1, Exception), f"Worker 1 raised: {r1}"
    assert not isinstance(r2, Exception), f"Worker 2 raised: {r2}"
    assert r1 is True
    assert r2 is True

    # Verify: exactly one invoice was created in the database
    async with db_manager.session() as session:
        invoices = (
            (await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(invoices) == 1, f"Expected exactly 1 invoice, found {len(invoices)}"


async def test_3_1_worker_crash_and_lease_reclaim(pg_env):
    """3.1: Simulated worker crash while in-flight. Lease expires and second worker
    reclaims the job without duplicate invoice creation."""
    db_manager = pg_env["db_manager"]
    storage = pg_env["storage"]
    tenant_id = pg_env["tenant_id"]

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="crash_test.xml", content=XML_CONTENT
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    # First worker processes the job and commits the invoice
    assert await coordinator.process_job(job_id) is True

    # Simulate crash: set job status back to PARSING with updated_at expired past lease
    async with db_manager.session() as session:
        await session.execute(
            update(ProcessingJobORM)
            .where(ProcessingJobORM.id == job_id)
            .values(
                status="PARSING",
                updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )

    # Second worker reclaims the expired job
    reclaim_coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await reclaim_coordinator.process_job(job_id) is True

    # Verify: no duplicate invoice rows created
    async with db_manager.session() as session:
        invoices = (
            (await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(invoices) == 1


async def test_3_2_concurrent_human_review_optimistic_locking(pg_env):
    """3.2: Concurrent approve vs reject with same If-Match revision on PostgreSQL.
    Atomic Compare-And-Swap guarantees exactly ONE succeeds and the other gets HTTP 409."""
    db_manager = pg_env["db_manager"]
    client = pg_env["client"]
    headers = pg_env["headers"]
    tenant_id = pg_env["tenant_id"]

    inv_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        doc = await _create_test_document(session, tenant_id, "doc_rev.pdf")
        # Pre-seed invoice in READY_FOR_REVIEW with revision=1
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc.id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0100109106",
            supplier_name="NCC Test",
            invoice_number="INV-REV-001",
            invoice_series="1C26TCC",
            issue_date=date(2026, 11, 10),
            currency="VND",
            subtotal=Decimal("500000.0000"),
            tax_total=Decimal("50000.0000"),
            amount_payable=Decimal("550000.0000"),
        )
        mr = MatchResultORM(
            tenant_id=tenant_id,
            invoice_id=inv_id,
            status="MATCHED",
            is_matched=True,
            requires_review=False,
            issues_json="[]",
        )
        session.add_all([inv, mr])
        await session.flush()

    h_rev1 = {**headers, "If-Match": "1"}

    # Run Approve and Reject simultaneously
    resp_approve, resp_reject = await asyncio.gather(
        client.post(
            f"/api/v1/invoices/{inv_id}/approve",
            headers=h_rev1,
            json={"notes": "Phê duyệt đồng thời"},
        ),
        client.post(
            f"/api/v1/invoices/{inv_id}/reject",
            headers=h_rev1,
            json={"reason": "Từ chối đồng thời"},
        ),
    )

    statuses = [resp_approve.status_code, resp_reject.status_code]
    assert 200 in statuses, f"Expected at least one 200 OK, got: {statuses}"
    assert 409 in statuses, f"Expected 409 Conflict for losing concurrent action, got: {statuses}"

    # Verify final database state: revision incremented to 2, exactly one winning state
    async with db_manager.session() as session:
        final_inv = await session.get(InvoiceORM, inv_id)
        assert final_inv.revision == 2
        assert final_inv.status in ("APPROVED", "REJECTED")


async def test_3_2_stale_revision_rejected_with_409(pg_env):
    """3.2: Stale revision request explicitly receives HTTP 409 Conflict."""
    client = pg_env["client"]
    headers = pg_env["headers"]
    db_manager = pg_env["db_manager"]
    tenant_id = pg_env["tenant_id"]

    inv_id = str(uuid.uuid4())
    async with db_manager.session() as session:
        doc = await _create_test_document(session, tenant_id, "doc_stale.pdf")
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc.id,
            revision=5,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0100109106",
            invoice_number="INV-STALE-001",
            amount_payable=Decimal("100000.0000"),
            subtotal=Decimal("100000.0000"),
            tax_total=Decimal("0.0000"),
        )
        session.add(inv)
        await session.flush()

    # Pass stale revision (e.g. revision 4 when current is 5)
    stale_headers = {**headers, "If-Match": "4"}
    resp = await client.patch(
        f"/api/v1/invoices/{inv_id}/revisions",
        headers=stale_headers,
        json={"patches": {"supplier_name": "New Name"}},
    )
    assert resp.status_code == 409
    assert "Stale revision" in resp.json()["detail"]


async def test_3_3_concurrent_accounting_export_skip_locked(pg_env):
    """3.3: Two concurrent export requests against real PostgreSQL using SELECT FOR UPDATE SKIP LOCKED.
    Neither invoice is claimed twice, no duplicate export batches."""
    db_manager = pg_env["db_manager"]
    client = pg_env["client"]
    headers = pg_env["headers"]
    tenant_id = pg_env["tenant_id"]

    inv_ids = [str(uuid.uuid4()) for _ in range(3)]
    async with db_manager.session() as session:
        for i, inv_id in enumerate(inv_ids):
            doc = await _create_test_document(session, tenant_id, f"exp_doc_{i}.pdf")
            session.add(
                InvoiceORM(
                    id=inv_id,
                    tenant_id=tenant_id,
                    document_id=doc.id,
                    revision=1,
                    status="APPROVED",
                    supplier_tax_id="0100109106",
                    supplier_name="NCC Export",
                    invoice_number=f"EXP-INV-{i:03d}",
                    invoice_series="1C26TCC",
                    issue_date=date(2026, 11, 10),
                    currency="VND",
                    subtotal=Decimal("100000.0000"),
                    tax_total=Decimal("10000.0000"),
                    amount_payable=Decimal("110000.0000"),
                )
            )
        await session.flush()

    # Two export requests post concurrently
    res1, res2 = await asyncio.gather(
        client.post("/api/v1/exports", headers=headers, json={"format": "json"}),
        client.post("/api/v1/exports", headers=headers, json={"format": "json"}),
    )

    assert res1.status_code == 200
    assert res2.status_code == 200

    batch1_invoices = res1.json()
    batch2_invoices = res2.json()

    claimed_ids_1 = {inv["id"] for inv in batch1_invoices}
    claimed_ids_2 = {inv["id"] for inv in batch2_invoices}

    # Mutual exclusion: NO invoice is in both batches
    intersection = claimed_ids_1.intersection(claimed_ids_2)
    assert len(intersection) == 0, f"Invoices claimed by both batches: {intersection}"

    # Total claimed across both batches equals the 3 seeded invoices
    all_claimed = claimed_ids_1.union(claimed_ids_2)
    assert all_claimed == set(inv_ids)

    # Verify all 3 invoices in PostgreSQL have status EXPORTED
    async with db_manager.session() as session:
        invoices = (
            (
                await session.execute(
                    select(InvoiceORM).where(
                        InvoiceORM.tenant_id == tenant_id, InvoiceORM.id.in_(inv_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert all(inv.status == "EXPORTED" for inv in invoices)


async def test_3_3_export_batch_durability_and_client_retry(pg_env):
    """3.3: Durable export receipt: client disconnects after export commit and retries download.
    Can re-retrieve the exact artifact via GET /api/v1/exports/batches/{batch_id}."""
    db_manager = pg_env["db_manager"]
    client = pg_env["client"]
    headers = pg_env["headers"]
    tenant_id = pg_env["tenant_id"]

    inv_id = str(uuid.uuid4())
    async with db_manager.session() as session:
        doc = await _create_test_document(session, tenant_id, "dur_doc.pdf")
        session.add(
            InvoiceORM(
                id=inv_id,
                tenant_id=tenant_id,
                document_id=doc.id,
                revision=1,
                status="APPROVED",
                supplier_tax_id="0100109106",
                supplier_name="NCC Durable",
                invoice_number="INV-DUR-001",
                amount_payable=Decimal("220000.0000"),
                subtotal=Decimal("200000.0000"),
                tax_total=Decimal("20000.0000"),
            )
        )
        await session.flush()

    # 1. Post export
    post_res = await client.post("/api/v1/exports", headers=headers, json={"format": "csv"})
    assert post_res.status_code == 200
    export_id = post_res.headers.get("X-Export-ID")
    export_sha = post_res.headers.get("X-Export-SHA256")
    assert export_id is not None
    assert export_sha is not None

    # 2. Simulate client retry / re-download from durable receipt
    get_res = await client.get(f"/api/v1/exports/batches/{export_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.content == post_res.content
    assert get_res.headers["X-Export-SHA256"] == export_sha


async def test_3_4_concurrent_duplicate_invoices_database_level_uniqueness(pg_env):
    """3.4: Two concurrent invoices with identical tenant, supplier_tax_id, series, number.
    PostgreSQL unique constraint 'uq_invoices_approved_exported' guarantees that
    at most ONE duplicate invoice can EVER be APPROVED or EXPORTED."""
    db_manager = pg_env["db_manager"]
    client = pg_env["client"]
    headers = pg_env["headers"]
    tenant_id = pg_env["tenant_id"]

    inv_id_1 = str(uuid.uuid4())
    inv_id_2 = str(uuid.uuid4())

    shared_supplier = "0109999888"
    shared_series = "1C26TCC"
    shared_number = "0009999"

    async with db_manager.session() as session:
        # Seed two distinct invoice records having the same business identity
        for i, inv_id in enumerate((inv_id_1, inv_id_2)):
            doc = await _create_test_document(session, tenant_id, f"dup_doc_{i}.pdf")
            session.add(
                InvoiceORM(
                    id=inv_id,
                    tenant_id=tenant_id,
                    document_id=doc.id,
                    revision=1,
                    status="READY_FOR_REVIEW",
                    supplier_tax_id=shared_supplier,
                    supplier_name="NCC Dup",
                    invoice_series=shared_series,
                    invoice_number=shared_number,
                    issue_date=date(2026, 11, 10),
                    currency="VND",
                    subtotal=Decimal("500000.0000"),
                    tax_total=Decimal("50000.0000"),
                    amount_payable=Decimal("550000.0000"),
                )
            )
            session.add(
                MatchResultORM(
                    tenant_id=tenant_id,
                    invoice_id=inv_id,
                    status="MATCHED",
                    is_matched=True,
                    requires_review=False,
                    issues_json="[]",
                )
            )
        await session.flush()

    h_rev1 = {**headers, "If-Match": "1"}

    # Two reviewers concurrently attempt to approve both duplicates
    res1, res2 = await asyncio.gather(
        client.post(
            f"/api/v1/invoices/{inv_id_1}/approve",
            headers=h_rev1,
            json={"notes": "Approve duplicate 1"},
        ),
        client.post(
            f"/api/v1/invoices/{inv_id_2}/approve",
            headers=h_rev1,
            json={"notes": "Approve duplicate 2"},
        ),
    )

    statuses = [res1.status_code, res2.status_code]
    # Exactly one invoice can be APPROVED; the other MUST be rejected or conflict (409)
    assert 200 in statuses, f"Expected one 200 OK, got: {statuses}"
    assert 409 in statuses, f"Expected other to get 409 Conflict, got: {statuses}"

    # Verify at database level: exactly ONE invoice is in status APPROVED
    async with db_manager.session() as session:
        approved_invoices = (
            (
                await session.execute(
                    select(InvoiceORM).where(
                        InvoiceORM.tenant_id == tenant_id,
                        InvoiceORM.id.in_([inv_id_1, inv_id_2]),
                        InvoiceORM.status == "APPROVED",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert (
            len(approved_invoices) == 1
        ), f"Invariant violated: {len(approved_invoices)} duplicate invoices were approved!"


async def test_3_1_redis_broker_connectivity():
    """3.1: Live Redis broker verification on port 6379."""
    settings = get_settings()
    redis = Redis.from_url(settings.REDIS_URL)
    pong = await redis.ping()
    assert pong is True
    await redis.aclose()
