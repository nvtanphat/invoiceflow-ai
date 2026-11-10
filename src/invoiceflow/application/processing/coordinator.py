import json
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute
from invoiceflow.application.processing.evidence_mapper import EvidenceMapper
from invoiceflow.application.processing.service import DocumentAIService
from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.application.reconciliation.stp_evaluator import STPEvaluation, STPEvaluator
from invoiceflow.config import get_settings
from invoiceflow.domain.invoices.models import InvoiceAggregate
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    InvoiceORM,
    ProcessingJobORM,
)
from invoiceflow.infrastructure.database.repositories import DocumentRepository, InvoiceRepository
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.signature_verifier import (
    SignatureVerifierPort,
    XMLSignatureVerifier,
)
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
from invoiceflow.infrastructure.llm.provider import LLMProviderPort
from invoiceflow.infrastructure.storage.service import StoragePort

logger = logging.getLogger(__name__)


def _error_code(exc: BaseException) -> str:
    return type(exc).__name__


_CLAIMABLE_STATUSES = ("QUEUED", "RECEIVED", "RETRYING")
_IN_FLIGHT_STATUSES = ("INSPECTING", "PARSING", "EXTRACTING", "VALIDATING")


class JobCoordinator:
    """Asynchronous job execution coordinator for document ingestion and processing."""

    def __init__(
        self,
        db_manager: DatabaseSessionManager,
        storage: StoragePort,
        xml_parser: Optional[SecureXMLParser] = None,
        pdf_inspector: Optional[PDFInspector] = None,
        layout_extractor: Optional[LayoutExtractor] = None,
        llm_adapter: Optional[LLMProviderPort] = None,
        docling_adapter: Optional[DoclingAdapter] = None,
        signature_verifier: Optional[SignatureVerifierPort] = None,
        stp_evaluator: Optional[STPEvaluator] = None,
        document_ai_service: Optional[DocumentAIService] = None,
    ):
        self._db_manager = db_manager
        self._storage = storage
        self._xml_parser = xml_parser or SecureXMLParser()
        self._pdf_inspector = pdf_inspector or PDFInspector()
        self._layout_extractor = layout_extractor or LayoutExtractor()
        self._llm_adapter = llm_adapter
        self._docling_adapter = docling_adapter or DoclingAdapter(
            fallback_extractor=self._layout_extractor
        )
        self._signature_verifier = signature_verifier or XMLSignatureVerifier()
        self._stp_evaluator = stp_evaluator or STPEvaluator()
        self._router = DocumentRouter()
        self._evidence_mapper = EvidenceMapper()

        self._document_ai_service = document_ai_service or DocumentAIService(
            xml_parser=self._xml_parser,
            pdf_inspector=self._pdf_inspector,
            layout_extractor=self._layout_extractor,
            llm_adapter=self._llm_adapter,
            docling_adapter=self._docling_adapter,
            signature_verifier=self._signature_verifier,
            router=self._router,
            evidence_mapper=self._evidence_mapper,
        )

    async def _apply_stp_decision(
        self,
        session: AsyncSession,
        job_id: str,
        invoice: InvoiceAggregate,
        stp_eval: STPEvaluation,
    ) -> None:
        details = {
            "gates": stp_eval.gates(),
            "stp_reasons": stp_eval.stp_reasons,
            "review_reasons": stp_eval.review_reasons,
        }
        action = "AUTO_APPROVED_STP" if stp_eval.accounting_approved else "ROUTED_TO_HUMAN_REVIEW"
        target_status = stp_eval.target_status.value
        try:
            await session.execute(
                update(InvoiceORM)
                .where(
                    InvoiceORM.tenant_id == str(invoice.tenant_id),
                    InvoiceORM.id == str(invoice.id),
                )
                .values(status=target_status)
            )
            await session.flush()
        except IntegrityError:
            # Race condition: duplicate invoice approved concurrently by another process
            target_status = "READY_FOR_REVIEW"
            action = "ROUTED_TO_HUMAN_REVIEW_CONCURRENT_DUPLICATE"
            details["review_reasons"].append(
                "CONCURRENT_DUPLICATE_DETECTED: A duplicate invoice was approved concurrently."
            )
            await session.execute(
                update(InvoiceORM)
                .where(
                    InvoiceORM.tenant_id == str(invoice.tenant_id),
                    InvoiceORM.id == str(invoice.id),
                )
                .values(status=target_status)
            )
        session.add(
            AuditLogORM(
                tenant_id=str(invoice.tenant_id),
                action=action,
                actor_id="system_stp",
                aggregate_type="INVOICE",
                aggregate_id=str(invoice.id),
                details_json=json.dumps(details),
            )
        )
        await session.execute(
            update(ProcessingJobORM)
            .where(ProcessingJobORM.id == job_id)
            .values(status=target_status, stage="COMPLETED")
        )

    @staticmethod
    async def _claim(session: AsyncSession, job_id: str) -> bool:
        now = datetime.now(timezone.utc)
        lease_cutoff = now - timedelta(seconds=get_settings().JOB_LEASE_SECONDS)
        res = await session.execute(
            update(ProcessingJobORM)
            .where(
                ProcessingJobORM.id == job_id,
                or_(
                    ProcessingJobORM.status.in_(_CLAIMABLE_STATUSES),
                    and_(
                        ProcessingJobORM.status.in_(_IN_FLIGHT_STATUSES),
                        ProcessingJobORM.updated_at < lease_cutoff,
                    ),
                ),
            )
            .values(status="INSPECTING", stage="INSPECTING", updated_at=now)
        )
        return res.rowcount == 1

    async def process_job(self, job_id: str) -> bool:
        """Processes a single processing job through the document ingestion pipeline."""
        async with self._db_manager.session() as session:
            if not await self._claim(session, job_id):
                # Finished, unknown, or held by another worker within its lease.
                return True
            job = await session.get(ProcessingJobORM, job_id)
            doc_repo = DocumentRepository(session)
            doc = await doc_repo.get_document(job.tenant_id, job.document_id)
            if not doc:
                job.status = "FAILED_PERMANENT"
                job.error_message = "Document record not found."
                return False
            existing = await InvoiceRepository(session).get_invoice_by_document(
                doc.tenant_id, doc.id
            )
            if existing is not None:
                # A previous attempt committed the invoice and its decision; repeating the
                # pipeline would re-decide an invoice a reviewer may already have changed.
                job.status = "APPROVED" if existing.status == "APPROVED" else "READY_FOR_REVIEW"
                job.stage = "COMPLETED"
                return True

        try:
            content = await self._storage.get(doc.storage_uri)

            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(stage="PARSING")
                )

            result = await self._document_ai_service.process_document(
                tenant_id=doc.tenant_id,
                document_id=doc.id,
                filename=doc.filename,
                content=content,
                mime_type=doc.mime_type,
            )

            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(stage="EXTRACTING")
                )

                inv_repo = InvoiceRepository(session)
                await inv_repo.create_invoice(result.invoice_aggregate)

                # Record audit logs for signature or Vision AI
                if result.route == ProcessingRoute.XML_DETERMINISTIC:
                    sig_status = result.invoice_aggregate.signature_status
                    audit_details = json.dumps(
                        {
                            "signature_status": sig_status.value if sig_status else "unknown",
                            "evidence_count": len(result.invoice_aggregate.evidence),
                        }
                    )
                    session.add(
                        AuditLogORM(
                            tenant_id=doc.tenant_id,
                            action="XMLDSIG_CHECKED",
                            aggregate_type="INVOICE",
                            aggregate_id=str(result.invoice_aggregate.id),
                            details_json=audit_details,
                        )
                    )

                if result.used_vision:
                    vision_audit = json.dumps(
                        {
                            "reason": result.fallback_reason,
                            "cost_usd": result.cost_usd,
                            "failure": result.provider_failure,
                            "latency_ms": result.latency_ms,
                        }
                    )
                    session.add(
                        AuditLogORM(
                            tenant_id=doc.tenant_id,
                            action="VISION_FALLBACK_EXECUTED",
                            aggregate_type="INVOICE",
                            aggregate_id=str(result.invoice_aggregate.id),
                            details_json=vision_audit,
                        )
                    )

                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(stage="VALIDATING")
                )

                reconciliation = ReconciliationService(session)
                invoice = result.invoice_aggregate
                policy = await reconciliation.effective_policy(invoice)
                match_report = await reconciliation.reconcile_invoice(invoice, policy=policy)
                stp_eval = self._stp_evaluator.evaluate(
                    invoice=invoice, match_report=match_report, policy=policy
                )
                await self._apply_stp_decision(session, job_id, invoice, stp_eval)

            return True

        except (TimeoutError, ConnectionError, OSError) as e:
            logger.warning(
                "Transient error on job %s: %s; flagging for retry", job_id, _error_code(e)
            )
            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(
                        status="RETRYING",
                        stage="RETRY",
                        error_message=f"TRANSIENT_ERROR: {_error_code(e)}",
                    )
                )
            raise e
        except Exception as e:
            # Exception text can quote document content, so only its type is logged/stored.
            logger.error("Permanent error on job %s: %s", job_id, _error_code(e))
            async with self._db_manager.session() as session:
                await session.execute(
                    update(ProcessingJobORM)
                    .where(ProcessingJobORM.id == job_id)
                    .values(
                        status="FAILED_PERMANENT",
                        stage="ERROR",
                        error_message=f"PROCESSING_FAILED: {_error_code(e)}",
                    )
                )
            return False
