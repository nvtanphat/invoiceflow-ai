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
from invoiceflow.config import Settings, get_settings
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
)
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
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
        self._digital_parser = DigitalPDFParser()
        self._table_extractor = StructureAwareTableExtractor()

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
        if is_xml:
            result = self._process_xml(tenant_id, document_id, filename, content)
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
            classification="xml_standard",
            has_rotated_pages=False,
            used_vision=False,
            cost_usd=0.0,
            raw_header=raw_header,
            raw_lines=raw_lines,
        )

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
            content = self._docling_adapter._normalize_page_rotation(content)

        route = self._router.decide_route(
            detected_kind="pdf",
            file_size_bytes=len(content),
            pdf_classification=profile.classification,
            table_count=profile.table_count,
            has_rotated_pages=has_rotated,
        )

        do_ocr = (
            route in (ProcessingRoute.DOCLING_OCR_STRUCTURED, ProcessingRoute.VISION_FALLBACK)
            or profile.classification == "pdf_scan"
        )
        canonical_doc = self._docling_adapter.extract_canonical(
            tenant_id=tenant_id,
            document_id=document_id,
            pdf_bytes=content,
            do_ocr=do_ocr,
        )

        table_lines, table_line_evidence = self._table_extractor.extract_lines_with_evidence(
            canonical_doc.tables
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

        has_invalid_table_lines = not table_lines or any(
            line.qty <= Decimal("0.0000") or line.unit_price <= Decimal("0.0000")
            for line in table_lines
        )
        has_valid_digital_lines = bool(digital_res.lines) and all(
            line.qty > Decimal("0.0000") and line.unit_price > Decimal("0.0000")
            for line in digital_res.lines
        )

        if profile.classification == "pdf_scan" and table_lines:
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
        parser_issues = list(digital_res.issues)

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
            elif profile.classification == "pdf_scan":
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

                doc_text_for_vision = "" if profile.classification == "pdf_scan" else full_text
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
                    # Preserve existing confident fields; only fill missing/invalid or scan
                    if not header["supplier_tax_id"] and vision_res.supplier_tax_id:
                        header["supplier_tax_id"] = vision_res.supplier_tax_id
                    elif (
                        header["supplier_tax_id"]
                        and vision_res.supplier_tax_id
                        and header["supplier_tax_id"] != vision_res.supplier_tax_id
                    ):
                        parser_issues.append(
                            f"FIELD_CONFLICT_SUPPLIER_TAX_ID: OCR={header['supplier_tax_id']} vs Vision={vision_res.supplier_tax_id}"
                        )
                        if profile.classification == "pdf_scan":
                            header["supplier_tax_id"] = vision_res.supplier_tax_id

                    if not header["supplier_name"] and vision_res.supplier_name:
                        header["supplier_name"] = vision_res.supplier_name
                    elif profile.classification == "pdf_scan" and vision_res.supplier_name:
                        header["supplier_name"] = vision_res.supplier_name

                    if profile.classification == "pdf_scan" and vision_res.buyer_tax_id:
                        header["buyer_tax_id"] = vision_res.buyer_tax_id
                    elif not header["buyer_tax_id"] and vision_res.buyer_tax_id:
                        header["buyer_tax_id"] = vision_res.buyer_tax_id

                    if profile.classification == "pdf_scan" and vision_res.buyer_name:
                        header["buyer_name"] = vision_res.buyer_name
                    elif not header["buyer_name"] and vision_res.buyer_name:
                        header["buyer_name"] = vision_res.buyer_name

                    if profile.classification == "pdf_scan" and vision_res.invoice_number:
                        header["invoice_number"] = vision_res.invoice_number
                    elif not header["invoice_number"] and vision_res.invoice_number:
                        header["invoice_number"] = vision_res.invoice_number

                    if profile.classification == "pdf_scan" and vision_res.invoice_series:
                        header["invoice_series"] = vision_res.invoice_series
                    elif not header["invoice_series"] and vision_res.invoice_series:
                        header["invoice_series"] = vision_res.invoice_series

                    if profile.classification == "pdf_scan" and vision_res.issue_date:
                        header["issue_date"] = vision_res.issue_date
                    elif not header["issue_date"] and vision_res.issue_date:
                        header["issue_date"] = vision_res.issue_date

                    if profile.classification == "pdf_scan" and vision_res.amount_payable > Decimal(
                        "0.0000"
                    ):
                        header["amount_payable"] = vision_res.amount_payable
                    elif header["amount_payable"] <= Decimal(
                        "0.0000"
                    ) and vision_res.amount_payable > Decimal("0.0000"):
                        header["amount_payable"] = vision_res.amount_payable

                    if profile.classification == "pdf_scan" and vision_res.subtotal > Decimal(
                        "0.0000"
                    ):
                        header["subtotal"] = vision_res.subtotal
                    elif header["subtotal"] <= Decimal("0.0000") and vision_res.subtotal > Decimal(
                        "0.0000"
                    ):
                        header["subtotal"] = vision_res.subtotal

                    if profile.classification == "pdf_scan" and vision_res.tax_total > Decimal(
                        "0.0000"
                    ):
                        header["tax_total"] = vision_res.tax_total
                    elif header["tax_total"] <= Decimal(
                        "0.0000"
                    ) and vision_res.tax_total > Decimal("0.0000"):
                        header["tax_total"] = vision_res.tax_total

                    if is_table_lines and chosen_lines and vision_res.line_items:
                        reconciled_lines: list[InvoiceLine] = []
                        for o_idx, o_line in enumerate(chosen_lines):
                            v_match = None
                            for vl in vision_res.line_items:
                                if vl.sku and o_line.sku_ref and vl.sku == o_line.sku_ref:
                                    v_match = vl
                                    break
                                elif vl.line_no == o_line.line_no:
                                    v_match = vl
                                    break

                            if v_match:
                                has_unrecovered_qty = any(
                                    iss
                                    in (
                                        "QTY_ZERO_OR_MISSING",
                                        "QTY_UNRECOVERED",
                                        "CELL_MERGE_SUSPECTED",
                                        "ARITHMETIC_MISMATCH",
                                    )
                                    for iss in o_line.issues
                                )
                                if has_unrecovered_qty and v_match.qty > Decimal("0.0000"):
                                    exp_amt = (v_match.qty * o_line.unit_price) - o_line.discount
                                    if abs(o_line.line_amount - exp_amt) < Decimal("0.0100"):
                                        cleaned_issues = [
                                            iss
                                            for iss in o_line.issues
                                            if iss
                                            not in (
                                                "QTY_ZERO_OR_MISSING",
                                                "QTY_UNRECOVERED",
                                                "ARITHMETIC_MISMATCH",
                                                "CELL_MERGE_SUSPECTED",
                                            )
                                        ]
                                        o_line = o_line.model_copy(
                                            update={
                                                "qty": v_match.qty,
                                                "raw_qty": str(v_match.qty),
                                                "sku_ref": o_line.sku_ref or v_match.sku,
                                                "issues": cleaned_issues,
                                            }
                                        )
                                        table_line_evidence.append(
                                            FieldEvidence(
                                                field_path=f"lines[{o_idx}].qty",
                                                source_kind="vision_llm",
                                                raw_value=str(v_match.qty),
                                                normalized_value=str(v_match.qty),
                                                confidence=0.95,
                                                extractor="openai_vision",
                                            )
                                        )
                            reconciled_lines.append(o_line)
                        chosen_lines = reconciled_lines
                    elif (not chosen_lines or has_zero_qty) and vision_res.line_items:
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
            except Exception as exc:
                provider_failure = str(exc)
                parser_issues.append(f"VISION_FALLBACK_EXCEPTION: {provider_failure}")
                logger.exception("Exception in Vision AI fallback: %s", exc)

        extracted_fields = {
            "supplier_tax_id": header["supplier_tax_id"],
            "supplier_name": header["supplier_name"],
            "invoice_number": header["invoice_number"],
            "amount_payable": str(header["amount_payable"]) if header["amount_payable"] else None,
        }
        evidence: list[FieldEvidence] = self._evidence_mapper.map_evidence(
            extracted_fields, canonical_doc
        )
        if is_table_lines and table_line_evidence:
            evidence.extend(table_line_evidence)
        elif used_vision and not is_table_lines:
            for line in chosen_lines:
                evidence.append(
                    FieldEvidence(
                        field_path=f"lines.{line.line_no}.line_amount",
                        source_kind="vision_llm",
                        raw_value=str(line.line_amount),
                        normalized_value=str(line.line_amount),
                        confidence=0.85,
                        extractor="openai_vision",
                        bbox=None,
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
