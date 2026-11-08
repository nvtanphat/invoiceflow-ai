from datetime import date
import json
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
)
from invoiceflow.infrastructure.database.models import AuditLogORM, DocumentORM, ProcessingJobORM
from invoiceflow.infrastructure.database.repositories import DocumentRepository, InvoiceRepository
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.signature_verifier import SignatureVerifierPort, XMLSignatureVerifier
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
        docling_adapter: Optional[DoclingAdapter] = None,
        signature_verifier: Optional[SignatureVerifierPort] = None,
    ):
        self._db_manager = db_manager
        self._storage = storage
        self._xml_parser = xml_parser
        self._pdf_inspector = pdf_inspector
        self._layout_extractor = layout_extractor
        self._llm_adapter = llm_adapter
        self._docling_adapter = docling_adapter or DoclingAdapter(fallback_extractor=layout_extractor)
        self._signature_verifier = signature_verifier or XMLSignatureVerifier()
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

        # Cryptographic verification of XMLDSig digital signature
        sig_res = self._signature_verifier.verify_xml_signature(content)
        invoice_aggregate.signature_status = sig_res.status

        # Add signature verification evidence
        invoice_aggregate.evidence.append(
            FieldEvidence(
                field_path="signature_verification",
                source_kind="xml_signature",
                raw_value=sig_res.signer_name or "Unknown Signer",
                normalized_value=sig_res.status.value,
                confidence=1.0 if sig_res.is_valid else 0.0,
                extractor="xml_signature_verifier",
            )
        )

        async with self._db_manager.session() as session:
            inv_repo = InvoiceRepository(session)
            await inv_repo.create_invoice(invoice_aggregate)

            # Record audit provenance for XMLDSig verification
            audit_details = json.dumps({
                "signature_status": sig_res.status.value,
                "is_valid": sig_res.is_valid,
                "signer_name": sig_res.signer_name,
                "issuer": sig_res.issuer,
                "certificate_serial": sig_res.certificate_serial,
                "valid_from": sig_res.valid_from.isoformat() if sig_res.valid_from else None,
                "valid_to": sig_res.valid_to.isoformat() if sig_res.valid_to else None,
                "details": sig_res.details,
            })
            audit = AuditLogORM(
                tenant_id=doc.tenant_id,
                action="XMLDSIG_VERIFIED",
                aggregate_type="INVOICE",
                aggregate_id=str(invoice_aggregate.id),
                details_json=audit_details,
            )
            session.add(audit)

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

        # Pass do_ocr dynamically based on inspection route
        canonical_doc = self._docling_adapter.extract_canonical(
            tenant_id=doc.tenant_id,
            document_id=doc.id,
            pdf_bytes=content,
            do_ocr=(route == ProcessingRoute.VISION_FALLBACK or inspection.classification == "SCANNED_IMAGE"),
        )

        # Extraction phase
        async with self._db_manager.session() as session:
            await session.execute(
                update(ProcessingJobORM)
                .where(ProcessingJobORM.id == job_id)
                .values(stage="EXTRACTING")
            )

        full_text = "\n".join([el.text for el in canonical_doc.elements])
        digital_parser = DigitalPDFParser()
        digital_res = digital_parser.parse(full_text)

        # 1. Deterministic Fast Path: Digital PDF with high text confidence
        if route == ProcessingRoute.PDF_DIGITAL and digital_res.is_confident:
            lines = [
                InvoiceLine(
                    line_no=line.line_no,
                    sku_ref=line.sku,
                    description=line.description,
                    unit=line.unit,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    discount=line.discount,
                    tax_rate=line.tax_rate,
                    line_amount=line.line_amount,
                )
                for line in digital_res.lines
            ]
            extracted_fields = {
                "supplier_tax_id": digital_res.supplier_tax_id,
                "supplier_name": digital_res.supplier_name,
                "invoice_number": digital_res.invoice_number,
                "amount_payable": str(digital_res.amount_payable),
            }
            evidence = self._evidence_mapper.map_evidence(extracted_fields, canonical_doc)
            invoice_aggregate = InvoiceAggregate(
                tenant_id=doc.tenant_id,
                document_id=doc.id,
                revision=1,
                status=InvoiceStatus.READY_FOR_REVIEW,
                supplier_tax_id=digital_res.supplier_tax_id,
                supplier_name=digital_res.supplier_name,
                buyer_tax_id=digital_res.buyer_tax_id,
                buyer_name=digital_res.buyer_name,
                invoice_number=digital_res.invoice_number,
                invoice_series=digital_res.invoice_series,
                issue_date=date.fromisoformat(digital_res.issue_date) if digital_res.issue_date else None,
                currency=digital_res.currency,
                subtotal=digital_res.subtotal,
                tax_total=digital_res.tax_total,
                amount_payable=digital_res.amount_payable,
                lines=lines,
                evidence=evidence,
            )
        else:
            # 2. Vision Fallback Path: Scanned, mixed, or unconfident digital PDFs
            image_bytes_list: list[bytes] = []
            import fitz
            doc_pdf = fitz.open(stream=content, filetype="pdf")
            max_pages = min(len(doc_pdf), 5)
            for p_no in range(max_pages):
                pix = doc_pdf.load_page(p_no).get_pixmap(dpi=150)
                image_bytes_list.append(pix.tobytes("png"))
            doc_pdf.close()

            image_payload = (
                image_bytes_list if len(image_bytes_list) > 1
                else (image_bytes_list[0] if image_bytes_list else None)
            )

            try:
                llm_result = await self._llm_adapter.extract_invoice_data(
                    document_text=full_text,
                    image_bytes=image_payload,
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
