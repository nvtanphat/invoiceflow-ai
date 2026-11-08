import logging
from typing import Optional
from sqlalchemy import select, update
from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute
from invoiceflow.application.processing.evidence_mapper import EvidenceMapper
from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
    VerificationStatus,
)
from invoiceflow.infrastructure.database.models import DocumentORM, ProcessingJobORM
from invoiceflow.infrastructure.database.repositories import DocumentRepository, InvoiceRepository
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
from invoiceflow.infrastructure.llm.provider import LLMProviderPort
from invoiceflow.infrastructure.storage.service import StoragePort

logger = logging.getLogger(__name__)


class JobCoordinator:
    def __init__(
        self,
        db_manager: DatabaseSessionManager,
        storage: StoragePort,
        xml_parser: SecureXMLParser,
        pdf_inspector: PDFInspector,
        layout_extractor: LayoutExtractor,
        llm_adapter: LLMProviderPort,
    ):
        self._db_manager = db_manager
        self._storage = storage
        self._xml_parser = xml_parser
        self._pdf_inspector = pdf_inspector
        self._layout_extractor = layout_extractor
        self._llm_adapter = llm_adapter
        self._router = DocumentRouter()
        self._evidence_mapper = EvidenceMapper()

    async def process_job(self, job_id: str) -> bool:
        """Processes a single processing job through the document ingestion pipeline."""
        async with self._db_manager.session() as session:
            stmt = select(ProcessingJobORM).where(ProcessingJobORM.id == job_id)
            res = await session.execute(stmt)
            job = res.scalar_one_or_none()
            if not job or job.status in ("READY_FOR_REVIEW", "APPROVED", "FAILED_PERMANENT"):
                return True  # idempotent no-op

            doc_repo = DocumentRepository(session)
            doc = await doc_repo.get_document(job.tenant_id, job.document_id)
            if not doc:
                job.status = "FAILED_PERMANENT"
                job.error_message = "Document record not found."
                return False

            job.status = "INSPECTING"
            job.stage = "INSPECTING"
            await session.flush()

        # Execute processing steps
        try:
            content = await self._storage.get(doc.storage_uri)

            # Determine route
            if doc.mime_type == "application/xml" or doc.filename.lower().endswith(".xml"):
                await self._process_xml(job_id, doc, content)
            else:
                await self._process_pdf(job_id, doc, content)

            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(status="READY_FOR_REVIEW", stage="COMPLETED")
                )
            return True
        except (TimeoutError, ConnectionError, OSError) as e:
            logger.warning("Transient error processing job %s: %s; flagging for retry", job_id, e)
            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(
                        status="RETRYING",
                        stage="RETRY",
                        error_message=f"Transient error: {str(e)}",
                    )
                )
            raise e
        except Exception as e:
            logger.exception("Permanent error processing job %s: %s", job_id, e)
            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(
                        status="FAILED_PERMANENT",
                        stage="ERROR",
                        error_message=str(e),
                    )
                )
            return False

    async def _process_xml(self, job_id: str, doc: DocumentORM, content: bytes) -> None:
        async with self._db_manager.session() as session:
            await session.execute(
                update(ProcessingJobORM)
                .where(ProcessingJobORM.id == job_id)
                .values(stage="PARSING")
            )

        invoice_aggregate = self._xml_parser.parse_invoice_xml(
            tenant_id=doc.tenant_id,
            document_id=doc.id,
            xml_content=content,
        )

        async with self._db_manager.session() as session:
            inv_repo = InvoiceRepository(session)
            await inv_repo.create_invoice(invoice_aggregate)

            reconciliation = ReconciliationService(session)
            await reconciliation.reconcile_invoice(invoice_aggregate)

    async def _process_pdf(self, job_id: str, doc: DocumentORM, content: bytes) -> None:
        inspection = self._pdf_inspector.inspect(content)
        route = self._router.decide_route(
            detected_kind="pdf",
            file_size_bytes=len(content),
            pdf_classification=inspection.classification,
        )

        async with self._db_manager.session() as session:
            await session.execute(
                update(ProcessingJobORM)
                .where(ProcessingJobORM.id == job_id)
                .values(stage="PARSING")
            )

        canonical_doc = self._layout_extractor.extract_canonical(
            tenant_id=doc.tenant_id,
            document_id=doc.id,
            pdf_bytes=content,
        )

        # Extraction phase
        async with self._db_manager.session() as session:
            await session.execute(
                update(ProcessingJobORM)
                .where(ProcessingJobORM.id == job_id)
                .values(stage="EXTRACTING")
            )

        # Render image for vision if scanned/mixed or insufficient text layer
        image_bytes: Optional[bytes] = None
        if inspection.classification in ("pdf_scan", "scanned", "mixed") or not inspection.has_sufficient_text:
            import fitz
            doc_pdf = fitz.open(stream=content, filetype="pdf")
            if len(doc_pdf) > 0:
                page = doc_pdf.load_page(0)
                pix = page.get_pixmap(dpi=150)
                image_bytes = pix.tobytes("png")
            doc_pdf.close()

        # Call LLM extraction
        full_text = "\n".join([el.text for el in canonical_doc.elements])
        try:
            llm_result = await self._llm_adapter.extract_invoice_data(
                document_text=full_text,
                image_bytes=image_bytes,
                budget_usd=0.05,
            )
            extracted_fields = {
                "supplier_tax_id": llm_result.supplier_tax_id,
                "supplier_name": llm_result.supplier_name,
                "invoice_number": llm_result.invoice_number,
                "amount_payable": str(llm_result.amount_payable),
            }
            evidence = self._evidence_mapper.map_evidence(extracted_fields, canonical_doc)

            lines = [
                InvoiceLine(
                    line_no=line.line_no,
                    description=line.description,
                    unit=line.unit,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    discount=line.discount,
                    tax_rate=line.tax_rate,
                    line_amount=line.line_amount,
                )
                for line in llm_result.line_items
            ]

            invoice_aggregate = InvoiceAggregate(
                tenant_id=doc.tenant_id,
                document_id=doc.id,
                revision=1,
                status=InvoiceStatus.READY_FOR_REVIEW,
                supplier_tax_id=llm_result.supplier_tax_id,
                supplier_name=llm_result.supplier_name,
                buyer_tax_id=llm_result.buyer_tax_id,
                buyer_name=llm_result.buyer_name,
                invoice_number=llm_result.invoice_number,
                invoice_series=llm_result.invoice_series,
                currency=llm_result.currency,
                subtotal=llm_result.subtotal,
                tax_total=llm_result.tax_total,
                amount_payable=llm_result.amount_payable,
                lines=lines,
                evidence=evidence,
            )
        except Exception as e:
            logger.error("Document extraction failed for job %s: %s", job_id, e)
            raise RuntimeError(f"Extraction failed for {doc.filename}: {e}") from e

        async with self._db_manager.session() as session:
            await session.execute(
                update(ProcessingJobORM)
                .where(ProcessingJobORM.id == job_id)
                .values(stage="VALIDATING")
            )
            inv_repo = InvoiceRepository(session)
            await inv_repo.create_invoice(invoice_aggregate)

            reconciliation = ReconciliationService(session)
            await reconciliation.reconcile_invoice(invoice_aggregate)
