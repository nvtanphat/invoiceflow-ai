import json
from pathlib import Path
import shutil
import tempfile
import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select

from invoiceflow.application.ingestion.preflight import IngestionPreflight
from invoiceflow.application.ingestion.service import IngestionService
from invoiceflow.application.processing.coordinator import JobCoordinator
from invoiceflow.application.review.service import ReviewService
from invoiceflow.infrastructure.database.models import (
    FieldEvidenceORM,
    InvoiceLineORM,
    InvoiceORM,
    ProcessingJobORM,
)
from invoiceflow.infrastructure.database.repositories import InvoiceRepository
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter
from invoiceflow.infrastructure.storage.exporter import DocumentExporter
from invoiceflow.infrastructure.storage.service import LocalStorageService

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.mark.asyncio
async def test_full_application_lifecycle_upload_to_export():
    """Verify complete application lifecycle with XML e-invoice:
    Upload -> Document AI -> JSON -> Review & Correct -> Approve -> Multi-format Export.
    """
    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        preflight = IngestionPreflight()
        tenant_id = str(uuid.uuid4())
        reviewer_id = str(uuid.uuid4())

        # 1. UPLOAD: Ingest electronic invoice
        xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <HDon>
          <DLHDon>
            <TTChung>
              <KHMSHDon>1</KHMSHDon>
              <KHHDon>1C26TAA</KHHDon>
              <SHDon>0008888</SHDon>
              <NLap>2026-03-02</NLap>
              <DVTTe>VND</DVTTe>
            </TTChung>
            <NDHDon>
              <NBan>
                <Ten>Cong ty TNHH Thiet bi Van phong Thang Long</Ten>
                <MST>0101234567</MST>
              </NBan>
              <NMua>
                <Ten>Cong ty Co phan Thuong mai Alpha VN</Ten>
                <MST>0109998888</MST>
              </NMua>
              <DSHHDVu>
                <HHDVu>
                  <STT>1</STT>
                  <THHDVu>May tinh xach tay Dell XPS 13 [DELL-XPS-13]</THHDVu>
                  <DVTinh>chiec</DVTinh>
                  <SLuong>2.0000</SLuong>
                  <DGia>25000000.0000</DGia>
                  <TSuat>10%</TSuat>
                  <ThTien>50000000.0000</ThTien>
                </HHDVu>
              </DSHHDVu>
              <TToan>
                <TgTCThue>50000000.0000</TgTCThue>
                <TgTThue>5000000.0000</TgTThue>
                <TgTTTBSo>55000000.0000</TgTTTBSo>
              </TToan>
            </NDHDon>
          </DLHDon>
          <DSCKS>
            <NBan><Signature>SignedValid</Signature></NBan>
          </DSCKS>
        </HDon>"""

        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename="inv_0008888.xml",
                content=xml_content,
            )
            job_id = job.id

        # 2. DOCUMENT AI: Pipeline execution
        coordinator = JobCoordinator(
            db_manager=db_manager,
            storage=storage,
            xml_parser=SecureXMLParser(),
            pdf_inspector=PDFInspector(),
            layout_extractor=LayoutExtractor(),
            llm_adapter=OpenAIAdapter(api_key=None),
        )

        success = await coordinator.process_job(job_id)
        assert success is True

        # 3. JSON EXTRACTION & REPOSITORY VERIFICATION
        invoice_id = None
        current_revision = None
        async with db_manager.session() as session:
            job_orm = (
                await session.execute(select(ProcessingJobORM).where(ProcessingJobORM.id == job_id))
            ).scalar_one()
            assert job_orm.status == "READY_FOR_REVIEW"

            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            inv = invoices[0]
            invoice_id = inv.id
            current_revision = inv.revision

            assert inv.invoice_number == "0008888"
            assert inv.supplier_tax_id == "0101234567"
            assert inv.amount_payable == Decimal("55000000.0000")
            assert inv.status == "READY_FOR_REVIEW"

            # Verify line items and evidence provenance
            lines_res = await session.execute(
                select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
            )
            lines = lines_res.scalars().all()
            assert len(lines) == 1
            assert lines[0].sku_ref == "DELL-XPS-13"
            assert lines[0].qty == Decimal("2.0000")
            assert lines[0].unit_price == Decimal("25000000.0000")

            ev_res = await session.execute(
                select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == invoice_id)
            )
            evidence = ev_res.scalars().all()
            assert len(evidence) > 0
            assert any(e.field_path == "amount_payable" for e in evidence)

        # 4. REVIEW & CORRECTION: Modify a field via ReviewService with optimistic concurrency
        async with db_manager.session() as session:
            review_svc = ReviewService(session)
            updated_inv = await review_svc.update_invoice_fields(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                expected_revision=current_revision,
                actor_id=reviewer_id,
                patches={
                    "supplier_name": "Công ty TNHH Thiết bị Văn phòng Thăng Long (Đã chuẩn hóa)"
                },
                reason="Chuẩn hóa tên nhà cung cấp theo đăng ký kinh doanh",
            )
            assert updated_inv.revision == current_revision + 1
            current_revision = updated_inv.revision

        # 5. APPROVE: Approve reviewed invoice
        async with db_manager.session() as session:
            review_svc = ReviewService(session)
            approved_inv = await review_svc.approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                expected_revision=current_revision,
                actor_id=reviewer_id,
                notes="Đã kiểm tra đối soát, đủ điều kiện hạch toán",
            )
            assert approved_inv.status == "APPROVED"
            assert approved_inv.revision == current_revision + 1

        # 6. EXPORT: Export approved invoices to CSV, JSON, and XLSX
        async with db_manager.session() as session:
            res = await session.execute(
                select(InvoiceORM).where(
                    InvoiceORM.tenant_id == tenant_id,
                    InvoiceORM.status == "APPROVED",
                )
            )
            approved_invoices = res.scalars().all()
            assert len(approved_invoices) == 1

            export_data = [
                {
                    "id": i.id,
                    "supplier_name": i.supplier_name or "",
                    "supplier_tax_id": i.supplier_tax_id or "",
                    "invoice_number": i.invoice_number or "",
                    "invoice_series": i.invoice_series or "",
                    "issue_date": i.issue_date.isoformat() if i.issue_date else "",
                    "currency": i.currency,
                    "subtotal": Decimal(str(i.subtotal)),
                    "tax_total": Decimal(str(i.tax_total)),
                    "amount_payable": Decimal(str(i.amount_payable)),
                    "status": i.status,
                }
                for i in approved_invoices
            ]

            # CSV Export
            csv_output = DocumentExporter.to_csv(export_data)
            assert "0008888" in csv_output
            assert "0101234567" in csv_output
            assert "55000000.0000" in csv_output

            # JSON Export
            json_output = DocumentExporter.to_json(export_data)
            parsed_json = json.loads(json_output)
            assert len(parsed_json) == 1
            assert parsed_json[0]["invoice_number"] == "0008888"
            assert parsed_json[0]["status"] == "APPROVED"

            # Excel XLSX Export
            excel_bytes = DocumentExporter.to_excel(export_data)
            assert len(excel_bytes) > 0
            assert excel_bytes[:4] == b"PK\x03\x04"

    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_full_application_lifecycle_scanned_pdf_upload_to_export():
    """Verify complete application lifecycle with real scanned PDF:
    Upload (PDF scan) -> Document AI (Docling + OCR + Vision API) -> JSON -> Review -> Approve -> Export.
    """
    fixture_path = ROOT_DIR / "benchmarks" / "fixtures" / "documents" / "case_03.pdf"
    if not fixture_path.exists():
        pytest.skip("Scanned PDF fixture case_03.pdf not found.")

    from invoiceflow.config import get_settings

    settings = get_settings()
    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY in ("mock-key", ""):
        pytest.skip("Live OPENAI_API_KEY is not configured for scanned PDF vision lifecycle test.")

    pdf_content = fixture_path.read_bytes()
    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        preflight = IngestionPreflight()
        tenant_id = str(uuid.uuid4())
        reviewer_id = str(uuid.uuid4())

        # 1. UPLOAD: Ingest real scanned PDF
        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename="case_03.pdf",
                content=pdf_content,
            )
            job_id = job.id

        # 2. DOCUMENT AI: Pipeline execution with real DocumentAIService & OpenAIAdapter
        coordinator = JobCoordinator(
            db_manager=db_manager,
            storage=storage,
            llm_adapter=OpenAIAdapter(),
        )

        success = await coordinator.process_job(job_id)
        assert success is True

        # 3. VERIFY EXTRACTED INVOICE IN DATABASE
        invoice_id = None
        current_revision = None
        async with db_manager.session() as session:
            job_orm = (
                await session.execute(select(ProcessingJobORM).where(ProcessingJobORM.id == job_id))
            ).scalar_one()
            assert job_orm.status == "READY_FOR_REVIEW"

            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            inv = invoices[0]
            invoice_id = inv.id
            current_revision = inv.revision

            assert inv.invoice_number == "0003412"
            assert inv.supplier_tax_id == "0105554321"
            assert inv.amount_payable == Decimal("9180000.0000")
            assert inv.status == "READY_FOR_REVIEW"

            lines_res = await session.execute(
                select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
            )
            lines = lines_res.scalars().all()
            assert len(lines) >= 1
            assert lines[0].qty == Decimal("10.0000")
            assert lines[0].unit_price == Decimal("850000.0000")
            assert lines[0].line_amount == Decimal("8500000.0000")

            ev_res = await session.execute(
                select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == invoice_id)
            )
            evidence = ev_res.scalars().all()
            assert len(evidence) > 0

        # 4. REVIEW & APPROVE
        async with db_manager.session() as session:
            review_svc = ReviewService(session)
            approved_inv = await review_svc.approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                expected_revision=current_revision,
                actor_id=reviewer_id,
                notes="Đã kiểm tra chứng từ quét thực tế, phê duyệt thanh toán",
            )
            assert approved_inv.status == "APPROVED"

        # 5. EXPORT: Multi-format verification
        async with db_manager.session() as session:
            res = await session.execute(
                select(InvoiceORM).where(
                    InvoiceORM.tenant_id == tenant_id,
                    InvoiceORM.status == "APPROVED",
                )
            )
            approved_invoices = res.scalars().all()
            assert len(approved_invoices) == 1

            export_data = [
                {
                    "id": i.id,
                    "supplier_name": i.supplier_name or "",
                    "supplier_tax_id": i.supplier_tax_id or "",
                    "invoice_number": i.invoice_number or "",
                    "invoice_series": i.invoice_series or "",
                    "issue_date": i.issue_date.isoformat() if i.issue_date else "",
                    "currency": i.currency,
                    "subtotal": Decimal(str(i.subtotal)),
                    "tax_total": Decimal(str(i.tax_total)),
                    "amount_payable": Decimal(str(i.amount_payable)),
                    "status": i.status,
                }
                for i in approved_invoices
            ]

            csv_output = DocumentExporter.to_csv(export_data)
            assert "0003412" in csv_output
            assert "0105554321" in csv_output
            assert "9180000.0000" in csv_output

            json_output = DocumentExporter.to_json(export_data)
            parsed_json = json.loads(json_output)
            assert len(parsed_json) == 1
            assert parsed_json[0]["invoice_number"] == "0003412"

            excel_bytes = DocumentExporter.to_excel(export_data)
            assert len(excel_bytes) > 0
            assert excel_bytes[:4] == b"PK\x03\x04"

    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
