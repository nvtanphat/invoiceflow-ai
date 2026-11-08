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
    from invoiceflow.infrastructure.database.repositories import DocumentRepository, InvoiceRepository
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
