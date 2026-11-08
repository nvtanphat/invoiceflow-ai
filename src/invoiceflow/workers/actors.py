import asyncio
import logging
import dramatiq
from invoiceflow.application.processing.coordinator import JobCoordinator
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
from invoiceflow.infrastructure.llm.factory import get_llm_adapter
from invoiceflow.infrastructure.messaging.broker import setup_broker
from invoiceflow.infrastructure.storage.service import LocalStorageService

logger = logging.getLogger(__name__)

broker = setup_broker()


@dramatiq.actor(max_retries=3, min_backoff=2000, max_backoff=60000)
def process_document_job(job_id: str) -> None:
    """Asynchronous worker actor consuming document processing jobs."""
    settings = get_settings()
    db_manager = DatabaseSessionManager(database_url=settings.DATABASE_URL)
    storage = LocalStorageService(base_dir=settings.LOCAL_STORAGE_DIR)
    xml_parser = SecureXMLParser()
    pdf_inspector = PDFInspector()
    layout_extractor = LayoutExtractor()
    llm_adapter = get_llm_adapter(settings)

    coordinator = JobCoordinator(
        db_manager=db_manager,
        storage=storage,
        xml_parser=xml_parser,
        pdf_inspector=pdf_inspector,
        layout_extractor=layout_extractor,
        llm_adapter=llm_adapter,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        success = loop.run_until_complete(coordinator.process_job(job_id))
        if not success:
            logger.error("Job %s did not complete successfully.", job_id)
            raise RuntimeError(f"Processing failed for job {job_id}")
    finally:
        loop.run_until_complete(db_manager.close())
        loop.close()
