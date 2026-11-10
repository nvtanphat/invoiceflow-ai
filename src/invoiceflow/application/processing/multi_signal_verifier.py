from decimal import Decimal
import logging
import re
from typing import Any, List, Optional

from invoiceflow.config import get_settings
from invoiceflow.domain.invoices.evidence_gate import UNLOCATED_IN_SOURCE
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    FieldVerificationState,
    InvoiceAggregate,
)

logger = logging.getLogger(__name__)

_TAX_ID_PATTERN = re.compile(r"^\d{10}(?:-\d{3})?$")
_MODEL_SOURCE_KIND = "vision_llm"
_MODEL_PROPOSED_REASON = (
    "Value proposed by Vision LLM; arithmetic consistency of model output is not verification"
)


def _is_model_sourced(evidence: Optional[FieldEvidence]) -> bool:
    return evidence is not None and evidence.source_kind == _MODEL_SOURCE_KIND


class MultiSignalVerifier:
    """Consolidates document signals across deterministic parsers, OCR,

    region retries, arithmetic consistency checks, and Vision candidates.
    Assigns normalized FieldVerificationState semantics to each extracted field.
    """

    def __init__(self, min_field_confidence: Optional[float] = None):
        self._min_confidence = (
            min_field_confidence
            if min_field_confidence is not None
            else get_settings().MIN_FIELD_CONFIDENCE
        )

    def verify_invoice(self, invoice: InvoiceAggregate) -> InvoiceAggregate:
        existing_evidence = {ev.field_path: ev for ev in invoice.evidence}
        consolidated_evidence: List[FieldEvidence] = []
        parser_issues = getattr(invoice, "parser_issues", []) or []

        # 1. Header Fields Verification
        header_fields = [
            ("supplier_tax_id", invoice.supplier_tax_id),
            ("supplier_name", invoice.supplier_name),
            ("buyer_tax_id", invoice.buyer_tax_id),
            ("buyer_name", invoice.buyer_name),
            ("invoice_number", invoice.invoice_number),
            ("invoice_series", invoice.invoice_series),
            ("issue_date", invoice.issue_date.isoformat() if invoice.issue_date else None),
            ("subtotal", str(invoice.subtotal) if invoice.subtotal else None),
            ("tax_total", str(invoice.tax_total) if invoice.tax_total is not None else None),
            ("amount_payable", str(invoice.amount_payable) if invoice.amount_payable else None),
        ]

        for field_name, field_value in header_fields:
            ev = existing_evidence.get(field_name)
            candidate_ev = existing_evidence.get(f"{field_name}.candidate_vision")

            state, reason = self._determine_header_state(
                field_name=field_name,
                field_value=field_value,
                existing_ev=ev,
                has_candidate_conflict=candidate_ev is not None,
                parser_issues=parser_issues,
                invoice=invoice,
            )

            if ev is not None:
                updated_ev = ev.model_copy(
                    update={
                        "verification_state": state,
                        "review_reason": reason or ev.review_reason,
                    }
                )
                consolidated_evidence.append(updated_ev)
            elif field_value is not None or state in (
                FieldVerificationState.MISSING,
                FieldVerificationState.CONFLICT,
            ):
                new_ev = FieldEvidence(
                    field_path=field_name,
                    source_kind="multi_signal_verifier",
                    raw_value=None,
                    normalized_value=str(field_value) if field_value is not None else None,
                    confidence=None,
                    extractor="multi_signal_verifier",
                    verification_state=state,
                    review_reason=reason,
                )
                consolidated_evidence.append(new_ev)

        # 2. Line Items Verification
        for idx, line in enumerate(invoice.lines):
            line_prefix = f"lines[{idx}]"
            line_issues = getattr(line, "issues", []) or []

            # Line Quantity
            qty_ev = existing_evidence.get(f"{line_prefix}.qty")
            qty_state, qty_reason = self._determine_line_qty_state(line, qty_ev, line_issues)
            if qty_ev is not None:
                consolidated_evidence.append(
                    qty_ev.model_copy(
                        update={
                            "verification_state": qty_state,
                            "review_reason": qty_reason or qty_ev.review_reason,
                        }
                    )
                )
            else:
                consolidated_evidence.append(
                    FieldEvidence(
                        field_path=f"{line_prefix}.qty",
                        source_kind="multi_signal_verifier",
                        raw_value=line.raw_qty,
                        normalized_value=str(line.qty),
                        confidence=None,
                        extractor="multi_signal_verifier",
                        verification_state=qty_state,
                        review_reason=qty_reason,
                    )
                )

            # Line Unit Price
            price_ev = existing_evidence.get(f"{line_prefix}.unit_price")
            if line.unit_price <= Decimal("0.0000"):
                price_state = FieldVerificationState.ZERO
            elif _is_model_sourced(price_ev):
                price_state = FieldVerificationState.MODEL_PROPOSED
            else:
                price_state = FieldVerificationState.VALID
            if price_ev is not None:
                consolidated_evidence.append(
                    price_ev.model_copy(
                        update={
                            "verification_state": price_state,
                            "review_reason": _MODEL_PROPOSED_REASON
                            if price_state == FieldVerificationState.MODEL_PROPOSED
                            else price_ev.review_reason,
                        }
                    )
                )

            # Line Amount & Arithmetic
            amt_ev = existing_evidence.get(f"{line_prefix}.line_amount")
            expected_amt = (line.qty * line.unit_price) - line.discount
            amt_consistent = (
                line.qty > Decimal("0.0000")
                and line.unit_price > Decimal("0.0000")
                and abs(line.line_amount - expected_amt) < Decimal("0.0100")
            )
            if line.line_amount <= Decimal("0.0000"):
                amt_state = FieldVerificationState.ZERO
                amt_reason = "Line amount is zero or negative"
            elif _is_model_sourced(amt_ev):
                amt_state = FieldVerificationState.MODEL_PROPOSED
                amt_reason = _MODEL_PROPOSED_REASON
            elif amt_consistent:
                amt_state = FieldVerificationState.ARITHMETICALLY_CONSISTENT
                amt_reason = "Line arithmetic verified: qty * price - discount == line_amount"
            elif any("ARITHMETIC_MISMATCH" in iss or "CONFLICT" in iss for iss in line_issues):
                amt_state = FieldVerificationState.INVALID
                amt_reason = f"Arithmetic mismatch: expected {expected_amt}, got {line.line_amount}"
            else:
                amt_state = FieldVerificationState.VALID
                amt_reason = None

            if amt_ev is not None:
                consolidated_evidence.append(
                    amt_ev.model_copy(
                        update={
                            "verification_state": amt_state,
                            "review_reason": amt_reason or amt_ev.review_reason,
                        }
                    )
                )
            else:
                consolidated_evidence.append(
                    FieldEvidence(
                        field_path=f"{line_prefix}.line_amount",
                        source_kind="multi_signal_verifier",
                        raw_value=line.raw_line_amount,
                        normalized_value=str(line.line_amount),
                        confidence=None,
                        extractor="multi_signal_verifier",
                        verification_state=amt_state,
                        review_reason=amt_reason,
                    )
                )

        # 3. Preserve other evidence (e.g. candidates, image preprocessing metadata)
        handled_prefixes = tuple([h[0] for h in header_fields] + ["lines["])
        for ev in invoice.evidence:
            if not any(ev.field_path.startswith(p) for p in handled_prefixes):
                consolidated_evidence.append(ev)
            elif ".candidate_vision" in ev.field_path:
                consolidated_evidence.append(
                    ev.model_copy(
                        update={
                            "verification_state": FieldVerificationState.MODEL_PROPOSED,
                            "review_reason": ev.review_reason
                            or "Candidate in conflict with primary extractor",
                        }
                    )
                )

        return invoice.model_copy(update={"evidence": consolidated_evidence})

    def _determine_header_state(
        self,
        field_name: str,
        field_value: Optional[str],
        existing_ev: Optional[FieldEvidence],
        has_candidate_conflict: bool,
        parser_issues: List[str],
        invoice: InvoiceAggregate,
    ) -> tuple[FieldVerificationState, Optional[str]]:
        # Conflict check
        if has_candidate_conflict or any(
            f"FIELD_CONFLICT_{field_name.upper()}" in p_iss for p_iss in parser_issues
        ):
            return FieldVerificationState.CONFLICT, f"Conflict detected on field {field_name}"

        # Missing check
        if field_value is None or (isinstance(field_value, str) and not field_value.strip()):
            return FieldVerificationState.MISSING, f"Field {field_name} is missing"

        # Field-specific validation
        if field_name in ("supplier_tax_id", "buyer_tax_id"):
            clean_tax = field_value.strip()
            if not _TAX_ID_PATTERN.match(clean_tax):
                return (
                    FieldVerificationState.INVALID,
                    f"Tax ID '{clean_tax}' does not conform to Vietnamese 10/13 digit standard",
                )

        if (
            _is_model_sourced(existing_ev)
            and existing_ev is not None
            and existing_ev.extractor != "xml_deterministic"
        ):
            return FieldVerificationState.MODEL_PROPOSED, _MODEL_PROPOSED_REASON

        # Parsers default unread totals to zero; their own report decides, not the value.
        if f"{field_name.upper()}_NOT_FOUND" in parser_issues:
            return (
                FieldVerificationState.MISSING,
                f"Field {field_name} was not found in the document",
            )
        if existing_ev is not None and existing_ev.review_reason == UNLOCATED_IN_SOURCE:
            return (
                FieldVerificationState.UNCERTAIN,
                f"Value of {field_name} could not be located in the source document",
            )

        if field_name == "amount_payable":
            if invoice.amount_payable <= Decimal("0.0000"):
                return FieldVerificationState.ZERO, "Amount payable is zero or negative"
            if invoice.is_arithmetic_balanced:
                return (
                    FieldVerificationState.ARITHMETICALLY_CONSISTENT,
                    "Amount payable verified by arithmetic balance: subtotal - discount + tax == amount_payable",
                )

        if field_name == "subtotal":
            if invoice.subtotal <= Decimal("0.0000"):
                return FieldVerificationState.ZERO, "Subtotal is zero or negative"
            if invoice.lines and abs(invoice.calculated_line_total - invoice.subtotal) < Decimal(
                "0.0100"
            ):
                return (
                    FieldVerificationState.ARITHMETICALLY_CONSISTENT,
                    "Subtotal matches exact sum of invoice lines",
                )

        # Confidence and source-kind checks
        if existing_ev is not None:
            if existing_ev.confidence is not None and existing_ev.confidence < self._min_confidence:
                return (
                    FieldVerificationState.UNCERTAIN,
                    f"Extraction confidence ({existing_ev.confidence:.2f}) below threshold",
                )

        return FieldVerificationState.VALID, None

    def _determine_line_qty_state(
        self,
        line: Any,
        qty_ev: Optional[FieldEvidence],
        line_issues: List[str],
    ) -> tuple[FieldVerificationState, Optional[str]]:
        if any("LINE_QTY_CONFLICT" in iss for iss in line_issues):
            return FieldVerificationState.CONFLICT, "Conflicting quantity candidate detected"

        if line.qty <= Decimal("0.0000") or any(
            iss in ("QTY_ZERO_OR_MISSING", "QTY_UNRECOVERED", "CELL_MERGE_SUSPECTED")
            for iss in line_issues
        ):
            return (
                FieldVerificationState.ZERO,
                "Line quantity is zero, missing, or merged with adjacent cell",
            )

        if qty_ev is not None and qty_ev.source_kind == "ocr_region_retry":
            return (
                FieldVerificationState.ARITHMETICALLY_CONSISTENT,
                "Quantity recovered and validated by region OCR arithmetic consistency",
            )

        if _is_model_sourced(qty_ev):
            return FieldVerificationState.MODEL_PROPOSED, _MODEL_PROPOSED_REASON

        if (
            qty_ev is not None
            and qty_ev.confidence is not None
            and qty_ev.confidence < self._min_confidence
        ):
            return (
                FieldVerificationState.UNCERTAIN,
                f"Quantity confidence ({qty_ev.confidence:.2f}) below threshold",
            )

        return FieldVerificationState.VALID, None
