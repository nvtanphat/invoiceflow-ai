from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import logging
import re
import time
from typing import Any, Optional, Union
from uuid import UUID
import fitz

from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute
from invoiceflow.application.processing.evidence_mapper import EvidenceMapper
from invoiceflow.application.processing.line_evidence_recovery import (
    ground_text_lines,
    recover_merged_quantities,
)
from invoiceflow.application.processing.vision_reconciliation import (
    VisionReconciler,
    vision_line_evidence,
)
from invoiceflow.application.processing.multi_signal_verifier import MultiSignalVerifier
from invoiceflow.config import Settings, get_settings
from invoiceflow.domain.documents.models import BoundingBox, CanonicalDocument
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
)
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter
from invoiceflow.infrastructure.document.image_preprocessor import ImagePreprocessor
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import ClassificationStr, PDFInspector
from invoiceflow.infrastructure.document.region_recoverer import RegionOCRRecoverer
from invoiceflow.infrastructure.document.signature_verifier import (
    SignatureVerifierPort,
    XMLSignatureVerifier,
)
from invoiceflow.infrastructure.document.table_extractor import StructureAwareTableExtractor
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter
from invoiceflow.infrastructure.llm.provider import LLMProviderPort

logger = logging.getLogger(__name__)


@dataclass
class DocumentAIResult:
    invoice_aggregate: InvoiceAggregate
    route: ProcessingRoute
    classification: str
    has_rotated_pages: bool
    used_vision: bool
    fallback_reason: Optional[str] = None
    provider_failure: Optional[str] = None
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    raw_header: dict[str, Any] = field(default_factory=dict)
    raw_lines: list[dict[str, Any]] = field(default_factory=list)


class DocumentAIService:
    """Unified Document AI Application Service.

    Coordinates document inspection, deterministic XML/digital PDF parsing,
    Docling with EasyOCR, structure-aware table extraction, and Vision AI fallback.
    Used identically across asynchronous worker jobs and Application QA harnesses.
    """

    def __init__(
        self,
        xml_parser: Optional[SecureXMLParser] = None,
        pdf_inspector: Optional[PDFInspector] = None,
        layout_extractor: Optional[LayoutExtractor] = None,
        llm_adapter: Optional[LLMProviderPort] = None,
        docling_adapter: Optional[DoclingAdapter] = None,
        signature_verifier: Optional[SignatureVerifierPort] = None,
        router: Optional[DocumentRouter] = None,
        evidence_mapper: Optional[EvidenceMapper] = None,
        image_preprocessor: Optional[ImagePreprocessor] = None,
        region_recoverer: Optional[RegionOCRRecoverer] = None,
        multi_signal_verifier: Optional[MultiSignalVerifier] = None,
        settings: Optional[Settings] = None,
    ):
        self._settings = settings or get_settings()
        self._xml_parser = xml_parser or SecureXMLParser()
        self._pdf_inspector = pdf_inspector or PDFInspector()
        self._layout_extractor = layout_extractor or LayoutExtractor()
        self._llm_adapter = llm_adapter or OpenAIAdapter()
        self._docling_adapter = docling_adapter or DoclingAdapter(
            fallback_extractor=self._layout_extractor
        )
        self._signature_verifier = signature_verifier or XMLSignatureVerifier()
        self._router = router or DocumentRouter()
        self._evidence_mapper = evidence_mapper or EvidenceMapper()
        self._image_preprocessor = image_preprocessor or ImagePreprocessor()
        self._region_recoverer = region_recoverer or RegionOCRRecoverer()
        self._multi_signal_verifier = multi_signal_verifier or MultiSignalVerifier()
        self._digital_parser = DigitalPDFParser()
        self._table_extractor = StructureAwareTableExtractor()
        self._vision_reconciler = VisionReconciler()

    async def process_document(
        self,
        tenant_id: Union[UUID, str],
        document_id: Union[UUID, str],
        filename: str,
        content: bytes,
        mime_type: Optional[str] = None,
    ) -> DocumentAIResult:
        start_time = time.perf_counter()
        is_xml = (
            (mime_type == "application/xml")
            or filename.lower().endswith(".xml")
            or content.strip().startswith(b"<?xml")
            or content.strip().startswith(b"<HDon")
        )
        is_image = (
            (mime_type and mime_type.startswith("image/"))
            or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"))
            or content.startswith(b"\x89PNG")
            or content.startswith(b"\xff\xd8")
        )
        if is_xml:
            result = self._process_xml(tenant_id, document_id, filename, content)
        elif is_image:
            result = await self._process_image(tenant_id, document_id, filename, content)
        else:
            result = await self._process_pdf(tenant_id, document_id, filename, content)

        result.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return result

    def _process_xml(
        self,
        tenant_id: Union[UUID, str],
        document_id: Union[UUID, str],
        filename: str,
        content: bytes,
    ) -> DocumentAIResult:
        inv_agg = self._xml_parser.parse_invoice_xml(
            tenant_id=tenant_id,
            document_id=document_id,
            xml_content=content,
        )
        sig_res = self._signature_verifier.verify_xml_signature(content)
        inv_agg.signature_status = sig_res.status
        inv_agg.evidence.append(
            FieldEvidence(
                field_path="signature_verification",
                source_kind="xml_signature",
                raw_value=sig_res.signer_name or "Unknown Signer",
                normalized_value=sig_res.status.value,
                confidence=1.0 if sig_res.is_valid else 0.0,
                extractor="xml_signature_verifier",
            )
        )
        inv_agg = self._multi_signal_verifier.verify_invoice(inv_agg)
        raw_lines = [
            {
                "line_no": line.line_no,
                "sku": line.sku_ref or "",
                "description": line.description,
                "qty": str(line.qty),
                "unit_price": str(line.unit_price),
                "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                "line_amount": str(line.line_amount),
            }
            for line in inv_agg.lines
        ]
        raw_header = {
            "supplier_tax_id": inv_agg.supplier_tax_id or "",
            "supplier_name": inv_agg.supplier_name or "",
            "buyer_tax_id": inv_agg.buyer_tax_id or "",
            "buyer_name": inv_agg.buyer_name or "",
            "invoice_number": inv_agg.invoice_number or "",
            "invoice_series": inv_agg.invoice_series or "",
            "issue_date": inv_agg.issue_date.isoformat() if inv_agg.issue_date else "",
            "currency": inv_agg.currency,
            "subtotal": str(inv_agg.subtotal),
            "tax_total": str(inv_agg.tax_total),
            "amount_payable": str(inv_agg.amount_payable),
        }
        return DocumentAIResult(
            invoice_aggregate=inv_agg,
            route=ProcessingRoute.XML_DETERMINISTIC,
            classification=ClassificationStr("xml_invoice"),
            has_rotated_pages=False,
            used_vision=False,
            cost_usd=0.0,
            raw_header=raw_header,
            raw_lines=raw_lines,
        )

    async def _process_image(
        self,
        tenant_id: Union[UUID, str],
        document_id: Union[UUID, str],
        filename: str,
        content: bytes,
    ) -> DocumentAIResult:
        prep_res = self._image_preprocessor.preprocess(content)
        result = await self._process_pdf(
            tenant_id=tenant_id,
            document_id=document_id,
            filename=filename,
            content=prep_res.pdf_bytes,
        )
        result.route = ProcessingRoute.IMAGE_PREPROCESSED_OCR

        # The viewer renders the stored original image, so bboxes found on the processed
        # page are mapped back through PDF scale, deskew and perspective correction.
        evidence_list = [
            ev.model_copy(update={"bbox": prep_res.transform.map_page_bbox_to_original(ev.bbox)})
            if ev.bbox is not None
            else ev
            for ev in result.invoice_aggregate.evidence
        ]
        result.invoice_aggregate.evidence = evidence_list
        evidence_list.append(
            FieldEvidence(
                field_path="image_preprocessing.quality",
                source_kind="image_preprocessing",
                raw_value=f"blur={prep_res.quality.blur_score}, brightness={prep_res.quality.brightness_mean}, contrast={prep_res.quality.contrast_std}",
                normalized_value="enhanced" if prep_res.transform.applied_enhancement else "clean",
                confidence=0.95,
                extractor="opencv_image_preprocessor",
                verification_state="verified",
            )
        )
        if prep_res.transform.applied_perspective:
            evidence_list.append(
                FieldEvidence(
                    field_path="image_preprocessing.perspective_correction",
                    source_kind="image_preprocessing",
                    raw_value=f"orig_dim={prep_res.transform.original_width}x{prep_res.transform.original_height}",
                    normalized_value=f"proc_dim={prep_res.transform.processed_width}x{prep_res.transform.processed_height}",
                    confidence=0.92,
                    extractor="opencv_image_preprocessor",
                    verification_state="verified",
                )
            )
        if prep_res.transform.applied_deskew:
            evidence_list.append(
                FieldEvidence(
                    field_path="image_preprocessing.deskew",
                    source_kind="image_preprocessing",
                    raw_value=f"angle={prep_res.transform.deskew_angle:.2f}",
                    normalized_value="deskewed",
                    confidence=0.90,
                    extractor="opencv_image_preprocessor",
                    verification_state="verified",
                )
            )

        return result

    @staticmethod
    def _line_evidence(
        header_evidence: list[FieldEvidence],
        lines: list[InvoiceLine],
        table_line_evidence: list[FieldEvidence],
        canonical_doc: CanonicalDocument,
        subtotal: Decimal,
        is_table_lines: bool,
        lines_from_vision: bool,
    ) -> list[FieldEvidence]:
        if is_table_lines:
            return table_line_evidence
        # Cells of a rejected table describe different rows than the chosen lines.
        kept = [ev for ev in table_line_evidence if ev.source_kind != "pdf_table"]
        if lines_from_vision:
            return kept + vision_line_evidence(lines)
        subtotal_located = any(
            ev.field_path == "subtotal" and ev.bbox is not None for ev in header_evidence
        )
        line_total = sum((line.line_amount for line in lines), Decimal("0.0000"))
        subtotal_confirmed = (
            subtotal_located and bool(lines) and abs(line_total - subtotal) < Decimal("0.0100")
        )
        return kept + ground_text_lines(lines, canonical_doc, subtotal_confirmed)

    async def _process_pdf(
        self,
        tenant_id: Union[UUID, str],
        document_id: Union[UUID, str],
        filename: str,
        content: bytes,
    ) -> DocumentAIResult:
        profile = self._pdf_inspector.inspect(content)
        has_rotated = profile.has_rotated_pages
        if has_rotated:
            content = self._docling_adapter._normalize_page_rotation(
                content, page_classifications=profile.page_classifications
            )

        route = self._router.decide_route(
            detected_kind="pdf",
            file_size_bytes=len(content),
            pdf_classification=profile.classification,
            table_count=profile.table_count,
            has_rotated_pages=has_rotated,
        )

        do_ocr = route in (
            ProcessingRoute.DOCLING_OCR_STRUCTURED,
            ProcessingRoute.VISION_FALLBACK,
        ) or profile.classification in ("pdf_scan", "scanned_pdf", "mixed", "mixed_pdf")
        canonical_doc = self._docling_adapter.extract_canonical(
            tenant_id=tenant_id,
            document_id=document_id,
            pdf_bytes=content,
            do_ocr=do_ocr,
            page_classifications=profile.page_classifications,
        )

        table_lines, table_line_evidence = self._table_extractor.extract_lines_with_evidence(
            canonical_doc.tables
        )
        table_lines, table_line_evidence = recover_merged_quantities(
            table_lines, table_line_evidence
        )
        full_text = "\n".join([el.text for el in canonical_doc.elements])
        digital_res = self._digital_parser.parse(full_text)

        header = {
            "supplier_tax_id": digital_res.supplier_tax_id or "",
            "supplier_name": digital_res.supplier_name or "",
            "buyer_tax_id": digital_res.buyer_tax_id or "",
            "buyer_name": digital_res.buyer_name or "",
            "invoice_number": digital_res.invoice_number or "",
            "invoice_series": digital_res.invoice_series or "",
            "issue_date": digital_res.issue_date or "",
            "currency": digital_res.currency,
            "subtotal": digital_res.subtotal,
            "tax_total": digital_res.tax_total,
            "amount_payable": digital_res.amount_payable,
        }

        chosen_lines: list[InvoiceLine] = []
        is_table_lines = False
        lines_from_vision = False

        has_invalid_table_lines = not table_lines or any(
            line.qty <= Decimal("0.0000") or line.unit_price <= Decimal("0.0000")
            for line in table_lines
        )
        has_valid_digital_lines = bool(digital_res.lines) and all(
            line.qty > Decimal("0.0000") and line.unit_price > Decimal("0.0000")
            for line in digital_res.lines
        )

        if profile.classification in ("pdf_scan", "scanned_pdf") and table_lines:
            chosen_lines = table_lines
            is_table_lines = True
        elif not has_invalid_table_lines:
            chosen_lines = table_lines
            is_table_lines = True
        elif has_valid_digital_lines and len(digital_res.lines) >= len(table_lines):
            chosen_lines = [
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
                    raw_qty=line.raw_qty,
                    raw_unit_price=line.raw_unit_price,
                    raw_line_amount=line.raw_line_amount,
                    issues=line.issues,
                )
                for line in digital_res.lines
            ]
        elif table_lines:
            chosen_lines = table_lines
            is_table_lines = True

        recovery_issues: list[str] = []
        if self._region_recoverer is not None:
            try:
                doc_pdf_rec = fitz.open(stream=content, filetype="pdf")
                if not header["supplier_tax_id"]:
                    rec_tax = self._region_recoverer.recover_missing_header_field(
                        doc_pdf_rec, page_index=0, field_name="supplier_tax_id"
                    )
                    if rec_tax and VisionReconciler._is_valid_tax_id(rec_tax[0]):
                        header["supplier_tax_id"] = rec_tax[0]
                        table_line_evidence.append(
                            FieldEvidence(
                                field_path="supplier_tax_id",
                                source_kind="ocr_region_retry",
                                raw_value=rec_tax[0],
                                normalized_value=rec_tax[0],
                                confidence=min(0.92, rec_tax[1]),
                                extractor="region_ocr_recoverer",
                                verification_state="verified",
                            )
                        )
                if not header["invoice_number"]:
                    rec_inv = self._region_recoverer.recover_missing_header_field(
                        doc_pdf_rec, page_index=0, field_name="invoice_number"
                    )
                    if rec_inv:
                        header["invoice_number"] = rec_inv[0]
                        table_line_evidence.append(
                            FieldEvidence(
                                field_path="invoice_number",
                                source_kind="ocr_region_retry",
                                raw_value=rec_inv[0],
                                normalized_value=rec_inv[0],
                                confidence=min(0.90, rec_inv[1]),
                                extractor="region_ocr_recoverer",
                                verification_state="verified",
                            )
                        )

                recovered_lines: list[InvoiceLine] = []
                for idx, line in enumerate(chosen_lines):
                    needs_qty_rec = (line.qty <= Decimal("0.0000")) or any(
                        iss
                        in (
                            "CELL_MERGE_SUSPECTED",
                            "QTY_ZERO_OR_MISSING",
                            "QTY_UNRECOVERED",
                            "ARITHMETIC_MISMATCH",
                        )
                        for iss in line.issues
                    )
                    if (
                        needs_qty_rec
                        and line.unit_price > Decimal("0.0000")
                        and line.line_amount > Decimal("0.0000")
                    ):
                        line_evs = [
                            ev
                            for ev in table_line_evidence
                            if ev.field_path.startswith(f"lines[{idx}].") and ev.bbox is not None
                        ]
                        target_bbox = None
                        target_page = 0
                        if line_evs:
                            target_page = line_evs[0].bbox.page_index
                            min_x0 = min(ev.bbox.x0 for ev in line_evs if ev.bbox.x0 is not None)
                            min_y0 = min(ev.bbox.y0 for ev in line_evs if ev.bbox.y0 is not None)
                            max_x1 = max(ev.bbox.x1 for ev in line_evs if ev.bbox.x1 is not None)
                            max_y1 = max(ev.bbox.y1 for ev in line_evs if ev.bbox.y1 is not None)
                            target_bbox = BoundingBox(
                                page_index=target_page,
                                x0=min_x0,
                                y0=min_y0,
                                x1=max_x1,
                                y1=max_y1,
                            )

                        rec_qty_res = self._region_recoverer.recover_line_quantity(
                            doc_pdf_rec,
                            page_index=target_page,
                            line_bbox=target_bbox,
                            unit_price=line.unit_price,
                            line_amount=line.line_amount,
                            discount=line.discount,
                        )
                        if rec_qty_res is not None:
                            cand_qty, rec_conf = rec_qty_res
                            cleaned_issues = [
                                iss
                                for iss in line.issues
                                if iss
                                not in (
                                    "CELL_MERGE_SUSPECTED",
                                    "QTY_ZERO_OR_MISSING",
                                    "QTY_UNRECOVERED",
                                    "ARITHMETIC_MISMATCH",
                                )
                            ]
                            line = line.model_copy(
                                update={
                                    "qty": cand_qty,
                                    "raw_qty": str(cand_qty),
                                    "issues": cleaned_issues,
                                }
                            )
                            table_line_evidence.append(
                                FieldEvidence(
                                    field_path=f"lines[{idx}].qty",
                                    source_kind="ocr_region_retry",
                                    raw_value=str(cand_qty),
                                    normalized_value=str(cand_qty),
                                    confidence=min(0.95, max(0.85, rec_conf)),
                                    extractor="region_ocr_recoverer",
                                    bbox=target_bbox,
                                    verification_state="arithmetically_consistent",
                                    review_reason="Recovered missing quantity validated by arithmetic consistency via Region OCR",
                                )
                            )
                    recovered_lines.append(line)
                chosen_lines = recovered_lines
                doc_pdf_rec.close()
            except Exception as exc:
                # Recovery is optional, but its failure must stay visible to review and ops.
                recovery_issues.append(f"REGION_RECOVERY_FAILED: {type(exc).__name__}")
                logger.warning("Region OCR recovery failed: %s", type(exc).__name__)

        has_zero_qty = any(line.qty <= Decimal("0.0000") for line in chosen_lines)
        has_line_issue = any(
            any(
                iss
                in (
                    "CELL_MERGE_SUSPECTED",
                    "QTY_ZERO_OR_MISSING",
                    "QTY_UNRECOVERED",
                    "ARITHMETIC_MISMATCH",
                )
                for iss in line.issues
            )
            for line in chosen_lines
        )
        missing_header = (
            not header["supplier_tax_id"]
            or not header["invoice_number"]
            or header["amount_payable"] <= Decimal("0.0000")
        )
        needs_vision = (
            route == ProcessingRoute.VISION_FALLBACK
            or not chosen_lines
            or has_zero_qty
            or has_line_issue
            or missing_header
        )

        used_vision = False
        fallback_reason: Optional[str] = None
        provider_failure: Optional[str] = None
        cost_usd = 0.0
        parser_issues = list(digital_res.issues) + recovery_issues
        vision_header_evidence: list[FieldEvidence] = []

        can_use_vision = False
        if self._llm_adapter is not None:
            if isinstance(self._llm_adapter, OpenAIAdapter):
                can_use_vision = self._llm_adapter._client is not None
            else:
                can_use_vision = True

        if needs_vision and can_use_vision:
            used_vision = True
            if missing_header:
                fallback_reason = "MISSING_HEADER_FIELDS"
            elif not chosen_lines:
                fallback_reason = "NO_LINES_EXTRACTED"
            elif has_line_issue or has_zero_qty:
                fallback_reason = "TABLE_CELL_MERGE_OR_UNRECOVERED_FIELDS"
            elif profile.classification in ("pdf_scan", "scanned_pdf"):
                fallback_reason = "SCANNED_PDF"
            else:
                fallback_reason = "VISION_FALLBACK_ROUTE"

            try:
                doc_pdf = fitz.open(stream=content, filetype="pdf")
                max_pages = min(len(doc_pdf), self._settings.MAX_DOCUMENT_PAGES)
                ocr_dpi = self._settings.OCR_DPI
                image_bytes_list: list[bytes] = []
                for p_no in range(max_pages):
                    pix = doc_pdf.load_page(p_no).get_pixmap(dpi=ocr_dpi)
                    image_bytes_list.append(pix.tobytes("jpeg"))
                doc_pdf.close()

                doc_text_for_vision = (
                    "" if profile.classification in ("pdf_scan", "scanned_pdf") else full_text
                )
                img_payload = (
                    image_bytes_list
                    if len(image_bytes_list) > 1
                    else (image_bytes_list[0] if image_bytes_list else None)
                )
                vision_res = await self._llm_adapter.extract_invoice_data(
                    document_text=doc_text_for_vision,
                    image_bytes=img_payload,
                    budget_usd=self._settings.MAX_PROVIDER_BUDGET_PER_DOC_USD,
                )

                if vision_res.raw_response and "error" in vision_res.raw_response:
                    provider_failure = str(vision_res.raw_response["error"])
                    parser_issues.append(f"VISION_FALLBACK_FAILED: {provider_failure}")
                    logger.error("Vision AI fallback failed: %s", provider_failure)
                else:
                    cost_usd = getattr(vision_res, "cost_usd", 0.0) or 0.0
                    self._vision_reconciler.reconcile_header(
                        header, vision_res, parser_issues, vision_header_evidence
                    )

                    if chosen_lines and vision_res.line_items:
                        chosen_lines = self._vision_reconciler.reconcile_lines(
                            chosen_lines,
                            vision_res.line_items,
                            table_line_evidence,
                            parser_issues,
                        )
                    elif (not chosen_lines) and vision_res.line_items:
                        v_lines: list[InvoiceLine] = []
                        for idx, item in enumerate(vision_res.line_items, start=1):
                            line_sku = item.sku or ""
                            line_desc = item.description
                            if "[" in line_desc:
                                m_sku = re.search(r"\[([A-Z0-9_-]+)\]", line_desc)
                                if m_sku:
                                    if not line_sku:
                                        line_sku = m_sku.group(1)
                                    line_desc = re.sub(
                                        r"\s*\[[A-Z0-9_-]+\]\s*", "", line_desc
                                    ).strip()

                            line_issues: list[str] = []
                            if item.qty <= Decimal("0.0000"):
                                line_issues.append("INVALID_ZERO_QUANTITY")
                            if item.unit_price <= Decimal("0.0000"):
                                line_issues.append("INVALID_ZERO_PRICE")

                            exp_amt = (item.qty * item.unit_price) - item.discount
                            if abs(item.line_amount - exp_amt) >= Decimal("0.0100"):
                                line_issues.append("ARITHMETIC_MISMATCH")

                            v_lines.append(
                                InvoiceLine(
                                    line_no=idx,
                                    sku_ref=line_sku if line_sku else None,
                                    description=line_desc,
                                    unit=item.unit,
                                    qty=item.qty,
                                    unit_price=item.unit_price,
                                    discount=item.discount,
                                    tax_rate=item.tax_rate,
                                    line_amount=item.line_amount,
                                    raw_qty=str(item.qty),
                                    raw_unit_price=str(item.unit_price),
                                    raw_line_amount=str(item.line_amount),
                                    issues=line_issues,
                                )
                            )
                        chosen_lines = v_lines
                        is_table_lines = False
                        lines_from_vision = True
            except Exception as exc:
                provider_failure = str(exc)
                parser_issues.append(f"VISION_FALLBACK_EXCEPTION: {provider_failure}")
                logger.exception("Exception in Vision AI fallback: %s", exc)

        evidence: list[FieldEvidence] = self._evidence_mapper.map_evidence(
            _groundable_header_fields(header, parser_issues), canonical_doc
        )
        if vision_header_evidence:
            evidence.extend(vision_header_evidence)
        evidence.extend(
            self._line_evidence(
                evidence,
                chosen_lines,
                table_line_evidence,
                canonical_doc,
                header["subtotal"],
                is_table_lines=is_table_lines,
                lines_from_vision=lines_from_vision,
            )
        )

        parsed_date = None
        if header.get("issue_date"):
            try:
                parsed_date = date.fromisoformat(header["issue_date"])
            except ValueError:
                pass

        inv_agg = InvoiceAggregate(
            tenant_id=tenant_id,
            document_id=document_id,
            revision=1,
            status=InvoiceStatus.READY_FOR_REVIEW,
            supplier_tax_id=header["supplier_tax_id"] if header["supplier_tax_id"] else None,
            supplier_name=header["supplier_name"] if header["supplier_name"] else None,
            buyer_tax_id=header["buyer_tax_id"] if header["buyer_tax_id"] else None,
            buyer_name=header["buyer_name"] if header["buyer_name"] else None,
            invoice_number=header["invoice_number"] if header["invoice_number"] else None,
            invoice_series=header["invoice_series"] if header["invoice_series"] else None,
            issue_date=parsed_date,
            currency=header.get("currency", "VND"),
            subtotal=header["subtotal"],
            tax_total=header["tax_total"],
            amount_payable=header["amount_payable"],
            lines=chosen_lines,
            evidence=evidence,
            parser_issues=parser_issues,
        )
        inv_agg = self._multi_signal_verifier.verify_invoice(inv_agg)

        raw_header = {
            "supplier_tax_id": header["supplier_tax_id"],
            "supplier_name": header["supplier_name"],
            "buyer_tax_id": header["buyer_tax_id"],
            "buyer_name": header["buyer_name"],
            "invoice_number": header["invoice_number"],
            "invoice_series": header["invoice_series"],
            "issue_date": header["issue_date"],
            "currency": header["currency"],
            "subtotal": str(header["subtotal"]),
            "tax_total": str(header["tax_total"]),
            "amount_payable": str(header["amount_payable"]),
        }
        raw_lines = [
            {
                "line_no": line.line_no,
                "sku": line.sku_ref or "",
                "description": line.description,
                "qty": str(line.qty),
                "unit_price": str(line.unit_price),
                "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                "line_amount": str(line.line_amount),
            }
            for line in chosen_lines
        ]

        return DocumentAIResult(
            invoice_aggregate=inv_agg,
            route=route,
            classification=profile.classification,
            has_rotated_pages=has_rotated,
            used_vision=used_vision,
            fallback_reason=fallback_reason,
            provider_failure=provider_failure,
            cost_usd=cost_usd,
            raw_header=raw_header,
            raw_lines=raw_lines,
        )


_HEADER_TEXT_FIELDS = (
    "supplier_tax_id",
    "supplier_name",
    "buyer_tax_id",
    "buyer_name",
    "invoice_number",
    "invoice_series",
    "issue_date",
)
_HEADER_MONEY_FIELDS = ("subtotal", "tax_total", "amount_payable")


def _groundable_header_fields(header: dict[str, Any], parser_issues: list[str]) -> dict[str, Any]:
    """Every extracted header value, except totals the parser reported as not found."""
    fields: dict[str, Any] = {name: header.get(name) or None for name in _HEADER_TEXT_FIELDS}
    for name in _HEADER_MONEY_FIELDS:
        if f"{name.upper()}_NOT_FOUND" not in parser_issues:
            fields[name] = str(header[name])
    return fields
