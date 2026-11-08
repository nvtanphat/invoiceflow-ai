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
    from invoiceflow.infrastructure.llm.provider import LLMProviderPort, ExtractionResult, ExtractedLine
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
            assert invoices[0].supplier_tax_id == "0101112233"
            assert invoices[0].invoice_number == "0009999"

            loaded_inv = await inv_repo.get_invoice(tenant_id=tenant_id, invoice_id=invoices[0].id)
            assert loaded_inv is not None
            assert len(loaded_inv.lines) == 1
            assert loaded_inv.lines[0].description == "San pham tu scan OCR"
    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


