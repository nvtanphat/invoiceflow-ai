import json
import logging
from typing import Optional
from sqlalchemy import select, update

from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute
from invoiceflow.application.processing.evidence_mapper import EvidenceMapper
from invoiceflow.application.processing.service import DocumentAIService
from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.application.reconciliation.stp_evaluator import STPEvaluator
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    InvoiceORM,
    ProcessingJobORM,
    TolerancePolicyORM,
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

    async def process_job(self, job_id: str) -> bool:
        """Processes a single processing job through the document ingestion pipeline."""
        async with self._db_manager.session() as session:
            stmt = select(ProcessingJobORM).where(ProcessingJobORM.id == job_id)
            res = await session.execute(stmt)
            job = res.scalar_one_or_none()
            if not job or job.status in ("READY_FOR_REVIEW", "APPROVED", "FAILED_PERMANENT"):
                return True

            doc_repo = DocumentRepository(session)
            doc = await doc_repo.get_document(job.tenant_id, job.document_id)
            if not doc:
                job.status = "FAILED_PERMANENT"
                job.error_message = "Document record not found."
                return False

            job.status = "INSPECTING"
            job.stage = "INSPECTING"
            await session.flush()

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
                match_report = await reconciliation.reconcile_invoice(result.invoice_aggregate)

                # Straight-Through Processing (STP) risk-based evaluation
                policy_stmt = select(TolerancePolicyORM).where(
                    TolerancePolicyORM.tenant_id == doc.tenant_id
                )
                policy_orm = (await session.execute(policy_stmt)).scalars().first()
                policy = (
                    TolerancePolicy(
                        tenant_id=doc.tenant_id,
                        auto_approve_threshold=policy_orm.auto_approve_threshold,
                        price_tolerance_pct=policy_orm.price_tolerance_pct,
                        qty_tolerance_pct=policy_orm.qty_tolerance_pct,
                        max_amount_delta=policy_orm.max_amount_delta,
                        separation_of_duties_required=policy_orm.separation_of_duties_required,
                    )
                    if policy_orm
                    else TolerancePolicy(tenant_id=doc.tenant_id)
                )

                stp_eval = self._stp_evaluator.evaluate(
                    invoice=result.invoice_aggregate,
                    match_report=match_report,
                    policy=policy,
                )

                if stp_eval.is_stp_eligible:
                    await session.execute(
                        update(InvoiceORM)
                        .where(InvoiceORM.id == str(result.invoice_aggregate.id))
                        .values(status="APPROVED")
                    )
                    session.add(
                        AuditLogORM(
                            tenant_id=doc.tenant_id,
                            action="AUTO_APPROVED_STP",
                            actor_id="system_stp",
                            aggregate_type="INVOICE",
                            aggregate_id=str(result.invoice_aggregate.id),
                            details_json=json.dumps({"stp_reasons": stp_eval.stp_reasons}),
                        )
                    )
                    await session.execute(
                        update(ProcessingJobORM)
                        .where(ProcessingJobORM.id == job_id)
                        .values(status="APPROVED", stage="COMPLETED")
                    )
                else:
                    session.add(
                        AuditLogORM(
                            tenant_id=doc.tenant_id,
                            action="ROUTED_TO_HUMAN_REVIEW",
                            actor_id="system_stp",
                            aggregate_type="INVOICE",
                            aggregate_id=str(result.invoice_aggregate.id),
                            details_json=json.dumps({"review_reasons": stp_eval.review_reasons}),
                        )
                    )
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
