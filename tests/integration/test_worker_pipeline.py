import uuid
import pytest
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.storage.service import LocalStorageService
import tempfile
import shutil


@pytest.mark.asyncio
async def test_worker_pipeline_processes_xml_job():
    from invoiceflow.application.processing.coordinator import JobCoordinator
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
    from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
    from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
    from invoiceflow.infrastructure.llm.gemini_adapter import GeminiAdapter
    from invoiceflow.application.ingestion.preflight import IngestionPreflight
    from invoiceflow.application.ingestion.service import IngestionService
    from invoiceflow.infrastructure.database.repositories import InvoiceRepository
    from invoiceflow.infrastructure.database.models import ProcessingJobORM

    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        preflight = IngestionPreflight()

        tenant_id = str(uuid.uuid4())
        xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <HDon>
          <DLHDon>
            <TTChung>
              <KHHDon>1C26TAA</KHHDon>
              <SHDon>0000099</SHDon>
              <NLap>2026-11-08</NLap>
              <DVTTe>VND</DVTTe>
            </TTChung>
            <NDHDon>
              <NBan><Ten>Cong Ty A</Ten><MST>0101112223</MST></NBan>
              <NMua><Ten>Cong Ty B</Ten><MST>0309998887</MST></NMua>
              <DSHHDVu>
                <HHDVu>
                  <STT>1</STT><THHDVu>Dich vu Cloud</THHDVu><SLuong>1</SLuong><DGia>5000000</DGia><ThTien>5000000</ThTien>
                </HHDVu>
              </DSHHDVu>
              <TToan><TgTCThue>5000000</TgTCThue><TgTThue>500000</TgTThue><TgTTTBSo>5500000</TgTTTBSo></TToan>
            </NDHDon>
          </DLHDon>
        </HDon>
        """

        # 1. Ingest document
        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename="invoice.xml",
                content=xml_content,
            )
            job_id = job.id

        # 2. Coordinate Job execution
        coordinator = JobCoordinator(
            db_manager=db_manager,
            storage=storage,
            xml_parser=SecureXMLParser(),
            pdf_inspector=PDFInspector(),
            layout_extractor=LayoutExtractor(),
            llm_adapter=GeminiAdapter(),
        )

        success = await coordinator.process_job(job_id)
        assert success is True

        # 3. Verify Job and Invoice in DB
        async with db_manager.session() as session:
            from sqlalchemy import select

            job_res = await session.execute(
                select(ProcessingJobORM).where(ProcessingJobORM.id == job_id)
            )
            final_job = job_res.scalar_one()
            assert final_job.status == "READY_FOR_REVIEW"

            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            assert invoices[0].invoice_number == "0000099"
            assert invoices[0].status == "READY_FOR_REVIEW"
    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_worker_pipeline_processes_digital_pdf_job():
    from invoiceflow.application.processing.coordinator import JobCoordinator
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
    from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
    from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
    from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter
    from invoiceflow.application.ingestion.preflight import IngestionPreflight
    from invoiceflow.application.ingestion.service import IngestionService
    from invoiceflow.infrastructure.database.repositories import InvoiceRepository
    from invoiceflow.infrastructure.database.models import ProcessingJobORM
    from pathlib import Path

    pdf_fixture = Path("benchmarks/fixtures/documents/case_02.pdf")
    if not pdf_fixture.exists():
        pytest.skip("Fixture case_02.pdf not found")

    pdf_content = pdf_fixture.read_bytes()

    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        preflight = IngestionPreflight()
        tenant_id = str(uuid.uuid4())

        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename="case_02.pdf",
                content=pdf_content,
            )
            job_id = job.id

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

        async with db_manager.session() as session:
            from sqlalchemy import select

            job_res = await session.execute(
                select(ProcessingJobORM).where(ProcessingJobORM.id == job_id)
            )
            final_job = job_res.scalar_one()
            assert final_job.status == "READY_FOR_REVIEW"

            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            assert invoices[0].status == "READY_FOR_REVIEW"
            assert invoices[0].supplier_tax_id == "0309876543"
            assert invoices[0].invoice_number == "0008890"
    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_worker_pipeline_processes_scan_pdf_job():
    from invoiceflow.application.processing.coordinator import JobCoordinator
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
    from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
    from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
    from invoiceflow.infrastructure.llm.provider import (
        LLMProviderPort,
        ExtractionResult,
        ExtractedLine,
    )
    from invoiceflow.application.ingestion.preflight import IngestionPreflight
    from invoiceflow.application.ingestion.service import IngestionService
    from invoiceflow.infrastructure.database.repositories import InvoiceRepository
    from invoiceflow.infrastructure.database.models import ProcessingJobORM
    from decimal import Decimal
    from pathlib import Path

    class MockVisionLLMAdapter(LLMProviderPort):
        async def extract_invoice_data(
            self,
            document_text: str,
            image_bytes=None,
            budget_usd: float = 0.05,
            request_id=None,
        ) -> ExtractionResult:
            return ExtractionResult(
                supplier_name="Cong ty TNHH Scan Test",
                supplier_tax_id="0101112233",
                buyer_name="Cong ty Alpha",
                buyer_tax_id="0309998887",
                invoice_number="0009999",
                invoice_series="1C26SAA",
                issue_date="2026-11-08",
                currency="VND",
                subtotal=Decimal("1000000.0000"),
                tax_total=Decimal("100000.0000"),
                amount_payable=Decimal("1100000.0000"),
                line_items=[
                    ExtractedLine(
                        line_no=1,
                        description="San pham tu scan OCR",
                        qty=Decimal("1.0000"),
                        unit_price=Decimal("1000000.0000"),
                        line_amount=Decimal("1000000.0000"),
                        tax_rate=Decimal("10.0000"),
                    )
                ],
                raw_response={"model": "mock-vision"},
                cost_usd=0.001,
            )

    pdf_fixture = Path("benchmarks/fixtures/documents/case_03.pdf")
    if not pdf_fixture.exists():
        pytest.skip("Fixture case_03.pdf not found")

    pdf_content = pdf_fixture.read_bytes()

    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        preflight = IngestionPreflight()
        tenant_id = str(uuid.uuid4())

        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename="case_03.pdf",
                content=pdf_content,
            )
            job_id = job.id

        coordinator = JobCoordinator(
            db_manager=db_manager,
            storage=storage,
            xml_parser=SecureXMLParser(),
            pdf_inspector=PDFInspector(),
            layout_extractor=LayoutExtractor(),
            llm_adapter=MockVisionLLMAdapter(),
        )

        success = await coordinator.process_job(job_id)
        assert success is True

        async with db_manager.session() as session:
            from sqlalchemy import select

            job_res = await session.execute(
                select(ProcessingJobORM).where(ProcessingJobORM.id == job_id)
            )
            final_job = job_res.scalar_one()
            assert final_job.status == "READY_FOR_REVIEW"

            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            assert invoices[0].status == "READY_FOR_REVIEW"
            assert invoices[0].supplier_tax_id == "0105554321"
            assert invoices[0].invoice_number == "0003412"

            loaded_inv = await inv_repo.get_invoice(tenant_id=tenant_id, invoice_id=invoices[0].id)
            assert loaded_inv is not None
            assert len(loaded_inv.lines) == 1
            assert "Bộ dụng cụ và hóa chất" in loaded_inv.lines[0].description
            assert any(e.field_path == "supplier_tax_id" for e in loaded_inv.evidence)
            assert any(e.field_path == "invoice_number" for e in loaded_inv.evidence)
    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_worker_pipeline_detects_and_blocks_arithmetic_mismatch():
    """Definition of Done: Upload real digital PDF with qty * unit_price != line_amount,
    verify worker creates invoice with critical arithmetic issue, and approval is blocked
    until reviewer corrects it.
    """
    import fitz
    import json
    from invoiceflow.application.processing.coordinator import JobCoordinator
    from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
    from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
    from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
    from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter
    from invoiceflow.application.ingestion.preflight import IngestionPreflight
    from invoiceflow.application.ingestion.service import IngestionService
    from invoiceflow.application.review.service import ReviewService
    from invoiceflow.infrastructure.database.models import MatchResultORM
    from invoiceflow.infrastructure.database.repositories import InvoiceRepository

    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        preflight = IngestionPreflight()
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        # Synthesize digital PDF with arithmetic discrepancy: qty 5 * unit_price 10,000,000 != line_amount 40,000,000
        pdf_doc = fitz.open()
        page = pdf_doc.new_page(width=595, height=842)
        text_lines = [
            "HOA DON GIA TRI GIA TANG",
            "Ky hieu: 1C26TAA",
            "So: 0001234",
            "Ngay: 2026-11-08",
            "Don vi ban: Cong Ty Thiet Bi Thang Long",
            "Ma so thue: 0101234567",
            "Don vi mua: Cong Ty Co Phan Alpha",
            "Ma so thue: 0309998887",
            "May tinh xach tay Dell 5 10000000 10% 40000000",
            "Cong tien hang: 40000000",
            "Tien thue GTGT: 4000000",
            "Tong cong: 44000000",
        ]
        y = 50
        for line_str in text_lines:
            page.insert_text((50, y), line_str, fontsize=11)
            y += 25
        pdf_bytes = pdf_doc.write()
        pdf_doc.close()

        # 1. Ingest via IngestionService
        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename="discrepancy_invoice.pdf",
                content=pdf_bytes,
                uploaded_by=user_id,
            )
            job_id = job.id

        # 2. Worker executes job coordinator
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

        # 3. Verify invoice created with validation issues
        async with db_manager.session() as session:
            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            invoice = invoices[0]
            assert invoice.status == "READY_FOR_REVIEW"
            assert invoice.invoice_number == "0001234"

            # Check MatchResultORM has LINE_ARITHMETIC_MISMATCH
            from sqlalchemy import select

            mr_res = await session.execute(
                select(MatchResultORM).where(MatchResultORM.invoice_id == invoice.id)
            )
            match_res = mr_res.scalars().first()
            assert match_res is not None
            assert match_res.requires_review is True
            assert match_res.is_matched is False

            issues = json.loads(match_res.issues_json)
            issue_codes = [i["code"] for i in issues]
            assert "LINE_ARITHMETIC_MISMATCH" in issue_codes

            # 4. Attempting approval MUST raise ValueError (blocking)
            review_svc = ReviewService(session)
            with pytest.raises(ValueError) as excinfo:
                await review_svc.approve_invoice(
                    tenant_id=tenant_id,
                    invoice_id=invoice.id,
                    expected_revision=1,
                    actor_id="independent_reviewer_id",
                    notes="Trying to approve invalid arithmetic",
                )
            assert "LINE_ARITHMETIC_MISMATCH" in str(excinfo.value) or "lỗi nghiêm trọng" in str(
                excinfo.value
            )

            # 5. Reviewer corrects line amount to 50,000,000, subtotal to 50,000,000, amount_payable to 55,000,000
            updated_inv = await review_svc.update_invoice_fields(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                expected_revision=1,
                actor_id="independent_reviewer_id",
                patches={
                    "lines": [{"line_no": 1, "line_amount": "50000000"}],
                    "subtotal": "50000000",
                    "tax_total": "5000000",
                    "amount_payable": "55000000",
                },
                reason="Corrected arithmetic mismatch: 5 * 10,000,000 = 50,000,000",
            )
            assert updated_inv.revision == 2

            # 6. Now approval succeeds without silent bypass
            approved = await review_svc.approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                expected_revision=2,
                actor_id="independent_reviewer_id",
                notes="Approved after line amount correction",
            )
            assert approved.status == "APPROVED"
            assert approved.revision == 3
    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
