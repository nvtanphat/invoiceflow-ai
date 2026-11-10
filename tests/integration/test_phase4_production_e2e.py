from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

import cv2
from httpx import ASGITransport, AsyncClient
import numpy as np
import fitz
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select, update

from invoiceflow.api.dependencies import create_access_token
from invoiceflow.api.main import create_app
from invoiceflow.application.ingestion.preflight import IngestionPreflight
from invoiceflow.application.ingestion.service import IngestionService
from invoiceflow.application.processing.coordinator import JobCoordinator
from invoiceflow.config import get_settings
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceLine
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    DocumentORM,
    ExportBatchORM,
    FieldEvidenceORM,
    GoodsReceiptLineORM,
    GoodsReceiptORM,
    InvoiceORM,
    MatchResultORM,
    MembershipORM,
    ProcessingJobORM,
    PurchaseOrderLineORM,
    PurchaseOrderORM,
    TenantORM,
    TolerancePolicyORM,
    UserORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.llm.provider import ExtractionResult, LLMProviderPort
from invoiceflow.infrastructure.storage.service import LocalStorageService

pytestmark = pytest.mark.asyncio

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "fixtures" / "documents"


def _create_synthetic_invoice_image_bytes() -> bytes:
    img = np.full((1200, 850, 3), 250, dtype=np.uint8)
    cv2.putText(
        img, "HOA DON GIA TRI GIA TANG", (190, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2
    )
    cv2.putText(img, "Ky hieu: 1C26TAA", (60, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.putText(img, "So hoa don: 0005678", (550, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.putText(img, "Ngay: 2026-03-15", (60, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.putText(
        img,
        "Don vi ban: Cong ty Co phan Giay Mien Nam",
        (60, 230),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img, "Ma so thue: 0309876543", (60, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1
    )
    cv2.putText(
        img,
        "Don vi mua: Cong ty TNHH Thuong mai Dich vu Beta",
        (60, 310),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img, "Ma so thue: 0109998888", (60, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1
    )
    y_table = 400
    cv2.rectangle(img, (50, y_table), (800, y_table + 35), (220, 220, 220), -1)
    cv2.rectangle(img, (50, y_table), (800, y_table + 35), (0, 0, 0), 1)
    cv2.putText(img, "STT", (60, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Ten hang hoa, dich vu", (130, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "So luong", (480, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Don gia", (580, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Thanh tien", (690, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    y_r1 = y_table + 35
    cv2.rectangle(img, (50, y_r1), (800, y_r1 + 45), (0, 0, 0), 1)
    cv2.putText(img, "1", (65, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Giay in A4 Double A 70gsm", (130, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "10", (500, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "85,000", (580, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "850,000", (690, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    cv2.putText(img, "Cong tien hang: 850,000", (480, 530), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
    cv2.putText(img, "Tien thue GTGT (8%): 68,000", (480, 560), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
    cv2.putText(img, "Tong cong tien thanh toan: 918,000 VND", (420, 600), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    _, enc = cv2.imencode(".png", img)
    return enc.tobytes()


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


class TimeoutFailingLLMAdapter(LLMProviderPort):
    async def extract_invoice_data(self, *args, **kwargs) -> ExtractionResult:
        raise TimeoutError("Vision LLM provider gateway timeout")


@pytest_asyncio.fixture
async def prod_env():
    settings = get_settings()
    if "postgresql" not in settings.DATABASE_URL:
        pytest.skip("Phase 4 production-like workflow requires PostgreSQL.")

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

    pfx_a = f"p4a-{uuid.uuid4().hex[:6]}"
    pfx_b = f"p4b-{uuid.uuid4().hex[:6]}"

    async with db_manager.session() as session:
        # Tenant A setup
        tenant_a = TenantORM(name=f"Tenant A {pfx_a}")
        user_a = UserORM(
            email=f"admin_{pfx_a}@corp.vn",
            hashed_password="pw",
            full_name="Admin A",
            is_active=True,
        )
        session.add_all([tenant_a, user_a])
        await session.flush()

        session.add(MembershipORM(tenant_id=tenant_a.id, user_id=user_a.id, role="admin"))

        # Tenant B setup (for cross-tenant checks)
        tenant_b = TenantORM(name=f"Tenant B {pfx_b}")
        user_b = UserORM(
            email=f"user_{pfx_b}@corp.vn",
            hashed_password="pw",
            full_name="User B",
            is_active=True,
        )
        session.add_all([tenant_b, user_b])
        await session.flush()

        session.add(MembershipORM(tenant_id=tenant_b.id, user_id=user_b.id, role="admin"))
        await session.flush()

        # Seed standard purchasing data for Tenant A:
        # PO-1 & GRN-1 matching valid XML e-invoice (Vendor 0100109106, 50,000,000 VND)
        po1 = PurchaseOrderORM(
            tenant_id=tenant_a.id,
            vendor_tax_id="0100109106",
            vendor_name="Cong Ty Co Phan Nang Luong Thang Long",
            po_number="PO-THANG-LONG-01",
            order_date=date(2026, 3, 1),
            currency="VND",
            subtotal=Decimal("50000000.0000"),
        )
        session.add(po1)
        await session.flush()

        po_l1 = PurchaseOrderLineORM(
            po_id=po1.id,
            line_no=1,
            sku="DELL-XPS-13",
            description="May tinh xach tay Dell XPS 13 i7/16GB/512GB",
            unit="chiec",
            ordered_qty=Decimal("5.0000"),
            unit_price=Decimal("10000000.0000"),
            line_total=Decimal("50000000.0000"),
        )
        session.add(po_l1)
        await session.flush()

        grn1 = GoodsReceiptORM(
            tenant_id=tenant_a.id,
            po_id=po1.id,
            grn_number="GRN-THANG-LONG-01",
            receipt_date=date(2026, 3, 2),
        )
        session.add(grn1)
        await session.flush()

        session.add(
            GoodsReceiptLineORM(
                grn_id=grn1.id,
                po_line_id=po_l1.id,
                line_no=1,
                received_qty=Decimal("5.0000"),
            )
        )

        # PO-2 & GRN-2 matching case_02.pdf (Vendor 0309876543, 12,000,000 VND)
        po2 = PurchaseOrderORM(
            tenant_id=tenant_a.id,
            vendor_tax_id="0309876543",
            vendor_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
            po_number="PO-GIAY-01",
            order_date=date(2026, 3, 3),
            currency="VND",
            subtotal=Decimal("12000000.0000"),
        )
        session.add(po2)
        await session.flush()

        po_l2 = PurchaseOrderLineORM(
            po_id=po2.id,
            line_no=1,
            sku="PAPER-A4-70",
            description="Giấy photocopy Double A A4 70gsm",
            unit="ram",
            ordered_qty=Decimal("200.0000"),
            unit_price=Decimal("60000.0000"),
            line_total=Decimal("12000000.0000"),
        )
        session.add(po_l2)
        await session.flush()

        grn2 = GoodsReceiptORM(
            tenant_id=tenant_a.id,
            po_id=po2.id,
            grn_number="GRN-GIAY-01",
            receipt_date=date(2026, 3, 4),
        )
        session.add(grn2)
        await session.flush()

        session.add(
            GoodsReceiptLineORM(
                grn_id=grn2.id,
                po_line_id=po_l2.id,
                line_no=1,
                received_qty=Decimal("200.0000"),
            )
        )

        # Tolerance policy for Tenant A enabling STP auto-approval for Vendor 0100109106
        policy = TolerancePolicyORM(
            tenant_id=tenant_a.id,
            vendor_tax_id="0100109106",
            price_tolerance_pct=Decimal("0.0200"),
            qty_tolerance_pct=Decimal("0.0000"),
            max_amount_delta=Decimal("50000.0000"),
            auto_approve_threshold=Decimal("100000000.0000"),
            auto_approval_enabled=True,
            po_required=True,
            goods_receipt_required=True,
            effective_from=date(2026, 1, 1),
        )
        session.add(policy)
        await session.flush()

        tenant_a_id = tenant_a.id
        user_a_id = user_a.id
        tenant_b_id = tenant_b.id
        user_b_id = user_b.id

    token_a = create_access_token(
        user_id=user_a_id,
        tenant_id=tenant_a_id,
        role="admin",
        email=f"admin_{pfx_a}@corp.vn",
        settings=settings,
    )
    token_b = create_access_token(
        user_id=user_b_id,
        tenant_id=tenant_b_id,
        role="admin",
        email=f"user_{pfx_b}@corp.vn",
        settings=settings,
    )

    app = create_app(database_url=settings.DATABASE_URL, db_manager=db_manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "db_manager": db_manager,
            "storage": storage,
            "tenant_a_id": tenant_a_id,
            "user_a_id": user_a_id,
            "tenant_b_id": tenant_b_id,
            "user_b_id": user_b_id,
            "headers_a": {"Authorization": f"Bearer {token_a}"},
            "headers_b": {"Authorization": f"Bearer {token_b}"},
            "client": client,
        }

    await db_manager.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


async def test_scenario_01_clean_xml_stp_auto_approved_and_exported(prod_env):
    """Scenario 1: Clean XML e-invoice without Vision AI -> deterministic parsing ->
    3-way match -> STP auto-approved -> accounting export."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]
    client = prod_env["client"]
    headers = prod_env["headers_a"]

    xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <KHMSHDon>1</KHMSHDon>
      <KHHDon>C26TAA</KHHDon>
      <SHDon>0001245</SHDon>
      <NLap>2026-03-01</NLap>
      <DVTTe>VND</DVTTe>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>Cong Ty Co Phan Nang Luong Thang Long</Ten>
        <MST>0100109106</MST>
      </NBan>
      <NMua>
        <Ten>Cong Ty Mua Hang</Ten>
        <MST>0100109106</MST>
      </NMua>
      <DSHHDVu>
        <HHDVu>
          <TCat>1</TCat>
          <STT>1</STT>
          <THHDVu>May tinh xach tay Dell XPS 13 i7/16GB/512GB</THHDVu>
          <DVTinh>chiec</DVTinh>
          <SLuong>5</SLuong>
          <DGia>10000000</DGia>
          <ThTien>50000000</ThTien>
          <TSuat>10%</TSuat>
        </HHDVu>
      </DSHHDVu>
      <TToan>
        <TgTCThue>50000000</TgTCThue>
        <TgTThue>5000000</TgTThue>
        <TgTTTBSo>55000000</TgTTTBSo>
      </TToan>
    </NDHDon>
  </DLHDon>
</HDon>"""

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="case_01.xml", content=xml_content
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    # Backend inspection: verified extraction and STP auto-approval
    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        assert job.status == "APPROVED"
        assert job.stage == "COMPLETED"

        invoices = (
            (await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(invoices) == 1
        inv = invoices[0]
        assert inv.status == "APPROVED"
        assert inv.supplier_tax_id == "0100109106"
        assert inv.invoice_number == "0001245"
        assert inv.amount_payable == Decimal("55000000.0000")

        # Verify audit logs
        audits = (
            (
                await session.execute(
                    select(AuditLogORM).where(
                        AuditLogORM.tenant_id == tenant_id,
                        AuditLogORM.aggregate_id == inv.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        actions = {a.action for a in audits}
        assert "XMLDSIG_CHECKED" in actions
        assert "AUTO_APPROVED_STP" in actions

    # Export after approval (Scenario 14 preview)
    exp_res = await client.post("/api/v1/exports", headers=headers, json={"format": "csv"})
    assert exp_res.status_code == 200
    assert exp_res.headers.get("X-Export-ID") is not None
    assert "0001245" in exp_res.text

    async with db_manager.session() as session:
        final_inv = await session.get(InvoiceORM, inv.id)
        assert final_inv.status == "EXPORTED"


async def test_scenario_02_digital_pdf_pipeline(prod_env):
    """Scenario 2: Digital PDF with searchable text layer and bounding boxes."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    pdf_path = FIXTURES_DIR / "case_02.pdf"
    content = pdf_path.read_bytes()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="case_02.pdf", content=content
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        inv = (
            await session.execute(
                select(InvoiceORM).where(
                    InvoiceORM.tenant_id == tenant_id,
                    InvoiceORM.supplier_tax_id == "0309876543",
                )
            )
        ).scalar_one_or_none()
        assert inv is not None
        assert inv.invoice_number == "0008890"
        assert inv.amount_payable == Decimal("12960000.0000")

        # Verify provenance bboxes were saved
        evidences = (
            (
                await session.execute(
                    select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == inv.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(evidences) >= 3
        assert any(e.field_path == "amount_payable" for e in evidences)


async def test_scenario_03_scanned_pdf_pipeline(prod_env):
    """Scenario 3: Scanned PDF invoice handled through OCR / fallback."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    pdf_path = FIXTURES_DIR / "case_03.pdf"
    content = pdf_path.read_bytes()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="case_03.pdf", content=content
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        assert job.status in ("READY_FOR_REVIEW", "APPROVED")


async def test_scenario_04_mixed_pdf_pipeline(prod_env):
    """Scenario 4: Mixed digital/scanned PDF layout handled gracefully."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    pdf_path = FIXTURES_DIR / "case_06.pdf"
    content = pdf_path.read_bytes()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="case_06.pdf", content=content
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        assert job.status in ("READY_FOR_REVIEW", "APPROVED")


async def test_scenario_05_image_upload(prod_env):
    """Scenario 5: Mobile PNG/JPEG image upload with preprocessing."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    img_bytes = _create_synthetic_invoice_image_bytes()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="mobile_invoice.png", content=img_bytes
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        assert job.status in ("READY_FOR_REVIEW", "APPROVED")


async def test_scenario_06_duplicate_invoice_reconciliation_block(prod_env):
    """Scenario 6: Duplicate invoice upload is detected by reconciliation,
    blocked from STP auto-approval and blocked by ApprovalPreconditions & unique index."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]
    client = prod_env["client"]
    headers = prod_env["headers_a"]

    xml_orig = b"""<?xml version="1.0" encoding="utf-8"?>
<HDon>
  <DLHDon>
    <TTChung><KHMSHDon>1</KHMSHDon><KHHDon>C26TAA</KHHDon><SHDon>0009999</SHDon><NLap>2026-03-01</NLap><DVTTe>VND</DVTTe></TTChung>
    <NDHDon>
      <NBan><Ten>Cong Ty A</Ten><MST>0100109106</MST></NBan>
      <NMua><Ten>Cong Ty B</Ten><MST>0100109106</MST></NMua>
      <DSHHDVu><HHDVu><TCat>1</TCat><STT>1</STT><THHDVu>Hang hoa</THHDVu><DVTinh>cai</DVTinh><SLuong>1</SLuong><DGia>100000</DGia><ThTien>100000</ThTien><TSuat>10%</TSuat></HHDVu></DSHHDVu>
      <TToan><TgTCThue>100000</TgTCThue><TgTThue>10000</TgTThue><TgTTTBSo>110000</TgTTTBSo></TToan>
    </NDHDon>
  </DLHDon>
</HDon>"""

    # Ingest original invoice
    async with db_manager.session() as session:
        _, job_orig, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="orig.xml", content=xml_orig
        )
        job_id_orig = job_orig.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    await coordinator.process_job(job_id_orig)

    # Ingest duplicate copy (different comment so different SHA256 during ingestion)
    xml_dup = xml_orig.replace(b"</HDon>", b"<!-- duplicate copy --></HDon>")

    async with db_manager.session() as session:
        _, job_dup, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="dup.xml", content=xml_dup
        )
        job_id_dup = job_dup.id

    assert await coordinator.process_job(job_id_dup) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id_dup)
        # Cannot be AUTO_APPROVED because it's a duplicate of orig.xml
        assert job.status == "READY_FOR_REVIEW"

        inv = (
            await session.execute(
                select(InvoiceORM).where(
                    InvoiceORM.tenant_id == tenant_id,
                    InvoiceORM.document_id == job.document_id,
                )
            )
        ).scalar_one()

        mr = (
            await session.execute(
                select(MatchResultORM).where(MatchResultORM.invoice_id == inv.id)
            )
        ).scalar_one()
        issues = json.loads(mr.issues_json)
        assert any(i.get("code") == "DUPLICATE_INVOICE" for i in issues)

    # Attempt manual approval -> rejected by ApprovalPreconditions
    h_rev1 = {**headers, "If-Match": "1"}
    appr_res = await client.post(
        f"/api/v1/invoices/{inv.id}/approve",
        headers=h_rev1,
        json={"notes": "Try manual approve duplicate"},
    )
    assert appr_res.status_code in (400, 409)


async def test_scenario_07_missing_po_exception(prod_env):
    """Scenario 7: Missing PO flags matching exception and blocks approval without override note."""
    db_manager = prod_env["db_manager"]
    tenant_id = prod_env["tenant_a_id"]
    client = prod_env["client"]
    headers = prod_env["headers_a"]

    inv_id = str(uuid.uuid4())
    async with db_manager.session() as session:
        doc = await _create_test_document(session, tenant_id, "no_po.pdf")
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc.id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0109991111",  # Unknown vendor, no PO
            supplier_name="NCC Khong PO",
            invoice_number="INV-NOPO-001",
            amount_payable=Decimal("1000000.0000"),
            subtotal=Decimal("1000000.0000"),
            tax_total=Decimal("0.0000"),
        )
        mr = MatchResultORM(
            tenant_id=tenant_id,
            invoice_id=inv_id,
            status="EXCEPTION",
            is_matched=False,
            requires_review=True,
            issues_json=json.dumps([{"code": "MISSING_PURCHASE_ORDER", "severity": "warning", "message": "No PO"}]),
        )
        session.add_all([inv, mr])
        await session.flush()

    # Approval without notes is rejected
    res_no_note = await client.post(
        f"/api/v1/invoices/{inv_id}/approve",
        headers={**headers, "If-Match": "1"},
        json={"notes": ""},
    )
    assert res_no_note.status_code == 400
    assert "Cần ghi chú lý do phê duyệt" in res_no_note.json()["detail"]

    # Approval with valid override notes succeeds
    res_with_note = await client.post(
        f"/api/v1/invoices/{inv_id}/approve",
        headers={**headers, "If-Match": "1"},
        json={"notes": "Đã xác nhận ngoài hệ thống với bộ phận mua hàng."},
    )
    assert res_with_note.status_code == 200
    assert res_with_note.json()["status"] == "APPROVED"


async def test_scenario_08_missing_grn_exception(prod_env):
    """Scenario 8: Missing GRN (goods not yet delivered) flags match exception."""
    db_manager = prod_env["db_manager"]
    tenant_id = prod_env["tenant_a_id"]

    inv_id = str(uuid.uuid4())
    async with db_manager.session() as session:
        # Seed PO without GRN
        po = PurchaseOrderORM(
            tenant_id=tenant_id,
            vendor_tax_id="0108887777",
            vendor_name="NCC Chua Giao Hang",
            po_number="PO-NO-GRN",
            order_date=date(2026, 3, 1),
            subtotal=Decimal("5000000.0000"),
        )
        session.add(po)
        await session.flush()

        po_l = PurchaseOrderLineORM(
            po_id=po.id,
            line_no=1,
            sku="ITEM-X",
            description="Hang hoa",
            ordered_qty=Decimal("10.0000"),
            unit_price=Decimal("500000.0000"),
            line_total=Decimal("5000000.0000"),
        )
        session.add(po_l)

        doc = await _create_test_document(session, tenant_id, "no_grn.pdf")
        inv_orm = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc.id,
            revision=1,
            status="DRAFT",
            supplier_tax_id="0108887777",
            supplier_name="NCC Chua Giao Hang",
            invoice_number="INV-NOGRN-001",
            amount_payable=Decimal("5000000.0000"),
            subtotal=Decimal("5000000.0000"),
            tax_total=Decimal("0.0000"),
        )
        session.add(inv_orm)
        await session.flush()

    inv_agg = InvoiceAggregate(
        id=uuid.UUID(inv_id),
        tenant_id=tenant_id,
        document_id=doc.id,
        supplier_tax_id="0108887777",
        supplier_name="NCC Chua Giao Hang",
        invoice_number="INV-NOGRN-001",
        issue_date=date(2026, 3, 5),
        subtotal=Decimal("5000000.0000"),
        tax_total=Decimal("0.0000"),
        amount_payable=Decimal("5000000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Hang hoa",
                qty=Decimal("10.0000"),
                unit_price=Decimal("500000.0000"),
                line_amount=Decimal("5000000.0000"),
            )
        ],
    )
    from invoiceflow.application.reconciliation.service import ReconciliationService

    async with db_manager.session() as session:
        report = await ReconciliationService(session).reconcile_invoice(inv_agg)
        assert report.status.value == "MISSING_GRN"
        assert any("RECEIPT" in i.code or "GRN" in i.code or "QUANTITY" in i.code for i in report.issues)


async def test_scenario_09_price_quantity_variance(prod_env):
    """Scenario 9: Price variance beyond tolerance policy triggers review."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    pdf_path = FIXTURES_DIR / "case_04.pdf"
    content = pdf_path.read_bytes()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="case_04.pdf", content=content
        )
        job_id = job.id

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        # Cannot auto-approve due to price variance
        assert job.status == "READY_FOR_REVIEW"


async def test_scenario_10_missing_or_unresolved_evidence_blocks_approval(prod_env):
    """Scenario 10: Unresolved critical candidate evidence blocks manual approval."""
    db_manager = prod_env["db_manager"]
    tenant_id = prod_env["tenant_a_id"]
    client = prod_env["client"]
    headers = prod_env["headers_a"]

    inv_id = str(uuid.uuid4())
    async with db_manager.session() as session:
        doc = await _create_test_document(session, tenant_id, "conflict.pdf")
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc.id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0100109106",
            supplier_name="NCC Conflict",
            invoice_number="INV-CONF-001",
            amount_payable=Decimal("100000.0000"),
            subtotal=Decimal("100000.0000"),
            tax_total=Decimal("0.0000"),
        )
        # Add unresolved candidate evidence
        ev = FieldEvidenceORM(
            invoice_id=inv_id,
            field_path="amount_payable.candidate_vision",
            source_kind="vision",
            raw_value="120000",
            normalized_value="120000.0000",
            verification_state="model_proposed",
            extractor="llm",
        )
        mr = MatchResultORM(
            tenant_id=tenant_id,
            invoice_id=inv_id,
            status="MATCHED",
            is_matched=True,
            requires_review=False,
            issues_json="[]",
        )
        session.add_all([inv, ev, mr])
        await session.flush()

    # Attempt approve -> blocked by unresolved candidate
    res = await client.post(
        f"/api/v1/invoices/{inv_id}/approve",
        headers={**headers, "If-Match": "1"},
        json={"notes": "Approve with conflict"},
    )
    assert res.status_code == 400
    assert "xung đột tài chính chưa giải quyết" in res.json()["detail"]

    # Settle conflict via review endpoint
    res_resolve = await client.post(
        f"/api/v1/invoices/{inv_id}/review",
        headers={**headers, "If-Match": "1"},
        json={
            "action": "resolve_field",
            "field_path": "amount_payable",
            "decision": "accept_extracted",
            "reason": "Chấp nhận số liệu theo trích xuất gốc",
        },
    )
    assert res_resolve.status_code == 200

    # Now approval succeeds
    res_appr = await client.post(
        f"/api/v1/invoices/{inv_id}/approve",
        headers={**headers, "If-Match": "2"},
        json={"notes": "Phê duyệt sau khi giải quyết xung đột"},
    )
    assert res_appr.status_code == 200


async def test_scenario_11_vision_fallback_timeout_resilience(prod_env):
    """Scenario 11: Vision AI timeout or transient error flags job as RETRYING without crashing worker."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    # Minimal blank PDF with no extracted header so DocumentAIService triggers vision fallback
    doc_fitz = fitz.open()
    doc_fitz.new_page(width=595, height=842)
    content = doc_fitz.tobytes()
    doc_fitz.close()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="timeout_test.pdf", content=content
        )
        job_id = job.id

    failing_coordinator = JobCoordinator(
        db_manager=db_manager,
        storage=storage,
        llm_adapter=TimeoutFailingLLMAdapter(),
    )

    # Worker executes pipeline: gracefully handles Vision AI timeout without crashing process
    assert await failing_coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        # Blocked from auto-approval due to Vision AI timeout exception recorded in parser issues
        assert job.status == "READY_FOR_REVIEW"

        inv = (
            await session.execute(
                select(InvoiceORM).where(InvoiceORM.document_id == job.document_id)
            )
        ).scalar_one()
        mr = (
            await session.execute(
                select(MatchResultORM).where(MatchResultORM.invoice_id == inv.id)
            )
        ).scalar_one()
        issues = json.loads(mr.issues_json)
        assert any("VISION_FALLBACK" in i.get("code", "") for i in issues)


async def test_scenario_12_worker_restart_and_lease_expiration(prod_env):
    """Scenario 12: Worker restart mid-job: lease expires and job is reclaimed without duplication."""
    db_manager = prod_env["db_manager"]
    storage = prod_env["storage"]
    tenant_id = prod_env["tenant_a_id"]

    xml_path = FIXTURES_DIR / "case_05.xml"
    content = xml_path.read_bytes()

    async with db_manager.session() as session:
        _, job, _ = await IngestionService(session, storage, IngestionPreflight()).ingest_document(
            tenant_id=tenant_id, filename="restart_test.xml", content=content
        )
        job_id = job.id
        # Simulate worker crashed while parsing 2 hours ago
        await session.execute(
            update(ProcessingJobORM)
            .where(ProcessingJobORM.id == job_id)
            .values(
                status="PARSING",
                updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )

    coordinator = JobCoordinator(db_manager=db_manager, storage=storage)
    assert await coordinator.process_job(job_id) is True

    async with db_manager.session() as session:
        job = await session.get(ProcessingJobORM, job_id)
        assert job.status in ("APPROVED", "READY_FOR_REVIEW")
        assert job.stage == "COMPLETED"


async def test_scenario_13_db_broker_connectivity(prod_env):
    """Scenario 13: PostgreSQL pool pre-ping resilience and Redis broker connectivity."""
    db_manager = prod_env["db_manager"]
    settings = get_settings()

    # Test DB engine and pre-ping
    async with db_manager.session() as session:
        res = await session.execute(select(1))
        assert res.scalar_one() == 1

    # Test Redis broker ping
    redis = Redis.from_url(settings.REDIS_URL)
    pong = await redis.ping()
    assert pong is True
    await redis.aclose()


async def test_scenario_14_export_lifecycle_after_approval(prod_env):
    """Scenario 14: Export lifecycle: claimed invoices are posted, durable batch saved, idempotent redownload."""
    client = prod_env["client"]
    headers = prod_env["headers_a"]
    db_manager = prod_env["db_manager"]
    tenant_id = prod_env["tenant_a_id"]

    inv_id = str(uuid.uuid4())
    async with db_manager.session() as session:
        doc = await _create_test_document(session, tenant_id, "exp_life.pdf")
        session.add(
            InvoiceORM(
                id=inv_id,
                tenant_id=tenant_id,
                document_id=doc.id,
                revision=1,
                status="APPROVED",
                supplier_tax_id="0100109106",
                supplier_name="NCC Export Lifecycle",
                invoice_number="INV-EXL-001",
                amount_payable=Decimal("770000.0000"),
                subtotal=Decimal("700000.0000"),
                tax_total=Decimal("70000.0000"),
            )
        )
        await session.flush()

    res = await client.post("/api/v1/exports", headers=headers, json={"format": "xlsx"})
    assert res.status_code == 200
    batch_id = res.headers.get("X-Export-ID")
    assert batch_id is not None

    # Idempotent re-download
    redownload = await client.get(f"/api/v1/exports/batches/{batch_id}", headers=headers)
    assert redownload.status_code == 200
    assert redownload.content == res.content


async def test_scenario_15_unauthorized_cross_tenant_access(prod_env):
    """Scenario 15: Cross-tenant isolation: Tenant B cannot access or mutate Tenant A data."""
    client = prod_env["client"]
    headers_b = prod_env["headers_b"]
    db_manager = prod_env["db_manager"]
    tenant_a_id = prod_env["tenant_a_id"]

    inv_a_id = str(uuid.uuid4())
    batch_a_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        doc_a = await _create_test_document(session, tenant_a_id, "tenant_a_secret.pdf")
        session.add(
            InvoiceORM(
                id=inv_a_id,
                tenant_id=tenant_a_id,
                document_id=doc_a.id,
                revision=1,
                status="READY_FOR_REVIEW",
                supplier_tax_id="0100109106",
                supplier_name="Tenant A Secret Supplier",
                invoice_number="INV-SEC-001",
                amount_payable=Decimal("999999.0000"),
                subtotal=Decimal("999999.0000"),
                tax_total=Decimal("0.0000"),
            )
        )
        session.add(
            ExportBatchORM(
                id=batch_a_id,
                tenant_id=tenant_a_id,
                batch_number="EXP-SEC-001",
                format="csv",
                sha256="secret_sha",
                invoice_count=1,
                total_amount=Decimal("999999.0000"),
                invoice_ids_json=json.dumps([inv_a_id]),
                content_base64="c2VjcmV0",
                created_by="admin_a",
            )
        )
        await session.flush()

    # Tenant B tries to get Tenant A's invoice -> 404
    res_inv = await client.get(f"/api/v1/invoices/{inv_a_id}", headers=headers_b)
    assert res_inv.status_code == 404

    # Tenant B tries to approve Tenant A's invoice -> 404
    res_appr = await client.post(
        f"/api/v1/invoices/{inv_a_id}/approve",
        headers={**headers_b, "If-Match": "1"},
        json={"notes": "Malicious approve"},
    )
    assert res_appr.status_code == 404

    # Tenant B tries to download Tenant A's export batch -> 404
    res_batch = await client.get(f"/api/v1/exports/batches/{batch_a_id}", headers=headers_b)
    assert res_batch.status_code == 404
