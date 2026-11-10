from decimal import Decimal
import logging
import re
from typing import Any, Optional

from invoiceflow.domain.documents.value_parsing import normalize_tax_id, parse_printed_date
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    InvoiceLine,
)

logger = logging.getLogger(__name__)

# Score of _score_line_match (SKU, price, amount and description agreement) below which an
# OCR line and a Vision line are not considered the same line; ties above it are ambiguous.
_MIN_LINE_MATCH_SCORE = 40.0


class VisionReconciler:
    """Merges a Vision LLM extraction into deterministic OCR/parser results.

    Deterministic values win; Vision fills only absent fields and otherwise records a
    competing `.candidate_vision` evidence for human resolution. Every Vision-originated
    value carries `vision_llm` provenance and no invented confidence.
    """

    @staticmethod
    def _is_valid_tax_id(tax_id: Optional[str]) -> bool:
        if not tax_id:
            return False
        clean = tax_id.strip()
        return bool(re.match(r"^\d{10}(?:-?\d{3})?$", clean))

    def reconcile_header(
        self,
        header: dict[str, Any],
        vision_res: Any,
        parser_issues: list[str],
        vision_header_evidence: list[FieldEvidence],
    ) -> None:
        # Layout-only differences (spaces in an MST, dd/mm/yyyy dates) are not conflicts.
        vision_res = _normalised_header_values(vision_res, parser_issues)
        for name in ("supplier_tax_id", "buyer_tax_id"):
            if header.get(name):
                header[name] = normalize_tax_id(header[name])
        if header.get("issue_date"):
            parsed = parse_printed_date(header["issue_date"])
            header["issue_date"] = parsed.isoformat() if parsed else header["issue_date"]

        if not header["supplier_tax_id"] and vision_res.supplier_tax_id:
            if self._is_valid_tax_id(vision_res.supplier_tax_id):
                header["supplier_tax_id"] = vision_res.supplier_tax_id
                vision_header_evidence.append(
                    FieldEvidence(
                        field_path="supplier_tax_id",
                        source_kind="vision_llm",
                        raw_value=vision_res.supplier_tax_id,
                        normalized_value=vision_res.supplier_tax_id,
                        confidence=None,
                        extractor="openai_vision",
                        verification_state="model_proposed",
                    )
                )
            else:
                parser_issues.append(f"INVALID_VISION_TAX_ID: {vision_res.supplier_tax_id}")
        elif (
            header["supplier_tax_id"]
            and vision_res.supplier_tax_id
            and header["supplier_tax_id"] != vision_res.supplier_tax_id
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_SUPPLIER_TAX_ID: OCR={header['supplier_tax_id']} vs Vision={vision_res.supplier_tax_id}"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="supplier_tax_id.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=vision_res.supplier_tax_id,
                    normalized_value=vision_res.supplier_tax_id,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting candidate from Vision AI",
                )
            )

        if not header["supplier_name"] and vision_res.supplier_name:
            header["supplier_name"] = vision_res.supplier_name
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="supplier_name",
                    source_kind="vision_llm",
                    raw_value=vision_res.supplier_name,
                    normalized_value=vision_res.supplier_name,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                )
            )
        elif (
            header["supplier_name"]
            and vision_res.supplier_name
            and header["supplier_name"].strip().lower() != vision_res.supplier_name.strip().lower()
        ):
            s1 = set(header["supplier_name"].lower().split())
            s2 = set(vision_res.supplier_name.lower().split())
            overlap = len(s1 & s2) / max(len(s1 | s2), 1)
            if overlap < 0.4:
                parser_issues.append(
                    f"FIELD_CONFLICT_SUPPLIER_NAME: OCR='{header['supplier_name']}' vs Vision='{vision_res.supplier_name}'"
                )
                vision_header_evidence.append(
                    FieldEvidence(
                        field_path="supplier_name.candidate_vision",
                        source_kind="vision_llm",
                        raw_value=vision_res.supplier_name,
                        normalized_value=vision_res.supplier_name,
                        confidence=None,
                        extractor="openai_vision",
                        verification_state="model_proposed",
                        review_reason="Conflicting candidate from Vision AI",
                    )
                )

        if not header["buyer_tax_id"] and vision_res.buyer_tax_id:
            if self._is_valid_tax_id(vision_res.buyer_tax_id):
                header["buyer_tax_id"] = vision_res.buyer_tax_id
                vision_header_evidence.append(
                    FieldEvidence(
                        field_path="buyer_tax_id",
                        source_kind="vision_llm",
                        raw_value=vision_res.buyer_tax_id,
                        normalized_value=vision_res.buyer_tax_id,
                        confidence=None,
                        extractor="openai_vision",
                        verification_state="model_proposed",
                    )
                )
        elif (
            header["buyer_tax_id"]
            and vision_res.buyer_tax_id
            and header["buyer_tax_id"] != vision_res.buyer_tax_id
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_BUYER_TAX_ID: OCR='{header['buyer_tax_id']}' vs Vision='{vision_res.buyer_tax_id}'"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="buyer_tax_id.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=vision_res.buyer_tax_id,
                    normalized_value=vision_res.buyer_tax_id,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting candidate from Vision AI",
                )
            )

        if not header["buyer_name"] and vision_res.buyer_name:
            header["buyer_name"] = vision_res.buyer_name

        if not header["invoice_number"] and vision_res.invoice_number:
            header["invoice_number"] = vision_res.invoice_number
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="invoice_number",
                    source_kind="vision_llm",
                    raw_value=vision_res.invoice_number,
                    normalized_value=vision_res.invoice_number,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                )
            )
        elif (
            header["invoice_number"]
            and vision_res.invoice_number
            and header["invoice_number"].lstrip("0") != vision_res.invoice_number.lstrip("0")
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_INVOICE_NUMBER: OCR='{header['invoice_number']}' vs Vision='{vision_res.invoice_number}'"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="invoice_number.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=vision_res.invoice_number,
                    normalized_value=vision_res.invoice_number,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting candidate from Vision AI",
                )
            )

        if not header["invoice_series"] and vision_res.invoice_series:
            header["invoice_series"] = vision_res.invoice_series
        elif (
            header["invoice_series"]
            and vision_res.invoice_series
            and header["invoice_series"].upper() != vision_res.invoice_series.upper()
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_INVOICE_SERIES: OCR='{header['invoice_series']}' vs Vision='{vision_res.invoice_series}'"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="invoice_series.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=vision_res.invoice_series,
                    normalized_value=vision_res.invoice_series,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting candidate from Vision AI",
                )
            )

        if not header["issue_date"] and vision_res.issue_date:
            header["issue_date"] = vision_res.issue_date
        elif (
            header["issue_date"]
            and vision_res.issue_date
            and header["issue_date"] != vision_res.issue_date
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_ISSUE_DATE: OCR='{header['issue_date']}' vs Vision='{vision_res.issue_date}'"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="issue_date.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=vision_res.issue_date,
                    normalized_value=vision_res.issue_date,
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting candidate from Vision AI",
                )
            )

        ocr_payable = header["amount_payable"]
        vis_payable = vision_res.amount_payable

        if ocr_payable > Decimal("0.0000"):
            if vis_payable > Decimal("0.0000") and abs(ocr_payable - vis_payable) >= Decimal(
                "1.0000"
            ):
                parser_issues.append(
                    f"FIELD_CONFLICT_AMOUNT_PAYABLE: OCR={ocr_payable} vs Vision={vis_payable}"
                )
                vision_header_evidence.append(
                    FieldEvidence(
                        field_path="amount_payable.candidate_vision",
                        source_kind="vision_llm",
                        raw_value=str(vis_payable),
                        normalized_value=str(vis_payable),
                        confidence=None,
                        extractor="openai_vision",
                        verification_state="model_proposed",
                        review_reason="Conflicting total proposed by Vision AI against OCR",
                    )
                )
        elif vis_payable > Decimal("0.0000"):
            header["amount_payable"] = vis_payable
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="amount_payable",
                    source_kind="vision_llm",
                    raw_value=str(vis_payable),
                    normalized_value=str(vis_payable),
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                )
            )

        if header["subtotal"] <= Decimal("0.0000") and vision_res.subtotal > Decimal("0.0000"):
            header["subtotal"] = vision_res.subtotal
            vision_header_evidence.append(_vision_evidence("subtotal", vision_res.subtotal))
        elif (
            header["subtotal"] > Decimal("0.0000")
            and vision_res.subtotal > Decimal("0.0000")
            and abs(header["subtotal"] - vision_res.subtotal) >= Decimal("1.0000")
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_SUBTOTAL: OCR={header['subtotal']} vs Vision={vision_res.subtotal}"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="subtotal.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=str(vision_res.subtotal),
                    normalized_value=str(vision_res.subtotal),
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting subtotal proposed by Vision AI against OCR",
                )
            )

        if header["tax_total"] <= Decimal("0.0000") and vision_res.tax_total > Decimal("0.0000"):
            header["tax_total"] = vision_res.tax_total
            vision_header_evidence.append(_vision_evidence("tax_total", vision_res.tax_total))
        elif (
            header["tax_total"] > Decimal("0.0000")
            and vision_res.tax_total > Decimal("0.0000")
            and abs(header["tax_total"] - vision_res.tax_total) >= Decimal("1.0000")
        ):
            parser_issues.append(
                f"FIELD_CONFLICT_TAX_TOTAL: OCR={header['tax_total']} vs Vision={vision_res.tax_total}"
            )
            vision_header_evidence.append(
                FieldEvidence(
                    field_path="tax_total.candidate_vision",
                    source_kind="vision_llm",
                    raw_value=str(vision_res.tax_total),
                    normalized_value=str(vision_res.tax_total),
                    confidence=None,
                    extractor="openai_vision",
                    verification_state="model_proposed",
                    review_reason="Conflicting tax total proposed by Vision AI against OCR",
                )
            )

    @staticmethod
    def _score_line_match(
        ocr_line: InvoiceLine,
        vis_line: Any,
        ocr_idx: int,
        vis_idx: int,
    ) -> float:
        score = 0.0

        o_sku = (ocr_line.sku_ref or "").strip().upper()
        v_sku = (vis_line.sku or "").strip().upper()
        if o_sku and v_sku:
            if o_sku == v_sku:
                score += 45.0
            elif o_sku in v_sku or v_sku in o_sku:
                score += 30.0
        elif v_sku and v_sku in ocr_line.description.upper():
            score += 25.0
        elif o_sku and o_sku in vis_line.description.upper():
            score += 25.0

        if ocr_line.unit_price > Decimal("0.0000") and vis_line.unit_price > Decimal("0.0000"):
            price_diff = abs(ocr_line.unit_price - vis_line.unit_price)
            if price_diff < Decimal("1.0000"):
                score += 35.0
            else:
                max_p = max(ocr_line.unit_price, vis_line.unit_price)
                if price_diff / max_p < Decimal("0.0200"):
                    score += 20.0
                else:
                    score -= 25.0

        if ocr_line.line_amount > Decimal("0.0000") and vis_line.line_amount > Decimal("0.0000"):
            amt_diff = abs(ocr_line.line_amount - vis_line.line_amount)
            if amt_diff < Decimal("1.0000"):
                score += 35.0
            else:
                max_a = max(ocr_line.line_amount, vis_line.line_amount)
                if amt_diff / max_a < Decimal("0.0200"):
                    score += 20.0
                else:
                    score -= 25.0

        o_tokens = set(re.findall(r"\w+", ocr_line.description.lower()))
        v_tokens = set(re.findall(r"\w+", vis_line.description.lower()))
        if o_tokens and v_tokens:
            jaccard = len(o_tokens & v_tokens) / len(o_tokens | v_tokens)
            score += jaccard * 30.0

        pos_bonus = max(0.0, 10.0 - abs(ocr_idx - vis_idx) * 3.0)
        score += pos_bonus

        return score

    def reconcile_lines(
        self,
        ocr_lines: list[InvoiceLine],
        vision_lines: list[Any],
        table_line_evidence: list[FieldEvidence],
        parser_issues: Optional[list[str]] = None,
    ) -> list[InvoiceLine]:
        num_ocr = len(ocr_lines)

        candidates: list[tuple[float, int, int]] = []
        scores_by_ocr: dict[int, list[tuple[float, int]]] = {i: [] for i in range(num_ocr)}

        for o_idx, o_line in enumerate(ocr_lines):
            for v_idx, v_line in enumerate(vision_lines):
                sc = self._score_line_match(o_line, v_line, o_idx, v_idx)
                candidates.append((sc, o_idx, v_idx))
                scores_by_ocr[o_idx].append((sc, v_idx))

        ambiguous_ocr_lines: set[int] = set()
        for o_idx, v_scores in scores_by_ocr.items():
            sorted_v = sorted(v_scores, key=lambda x: x[0], reverse=True)
            if (
                len(sorted_v) >= 2
                and sorted_v[0][0] >= _MIN_LINE_MATCH_SCORE
                and sorted_v[1][0] >= _MIN_LINE_MATCH_SCORE
                and (sorted_v[0][0] - sorted_v[1][0]) < 10.0
            ):
                ambiguous_ocr_lines.add(o_idx)

        candidates.sort(key=lambda x: x[0], reverse=True)
        matched_ocr: dict[int, tuple[int, float]] = {}
        used_vis: set[int] = set()

        for sc, o_idx, v_idx in candidates:
            if sc < _MIN_LINE_MATCH_SCORE:
                break
            if o_idx in matched_ocr or v_idx in used_vis:
                continue
            if o_idx in ambiguous_ocr_lines:
                continue
            matched_ocr[o_idx] = (v_idx, sc)
            used_vis.add(v_idx)

        reconciled_lines: list[InvoiceLine] = []
        for o_idx, o_line in enumerate(ocr_lines):
            if o_idx in ambiguous_ocr_lines:
                issues = list(o_line.issues)
                if "LINE_MATCH_AMBIGUOUS" not in issues:
                    issues.append("LINE_MATCH_AMBIGUOUS")
                if parser_issues is not None:
                    parser_issues.append(f"LINE_MATCH_AMBIGUOUS: Line {o_idx + 1}")
                reconciled_lines.append(o_line.model_copy(update={"issues": issues}))
                continue

            if o_idx not in matched_ocr:
                reconciled_lines.append(o_line)
                continue

            v_idx, _ = matched_ocr[o_idx]
            v_match = vision_lines[v_idx]

            # Case 1: OCR has a valid positive quantity (> 0).
            # Under P0 Financial Integrity, never allow Vision to overwrite OCR valid quantity!
            if o_line.qty > Decimal("0.0000"):
                if v_match.qty > Decimal("0.0000") and abs(o_line.qty - v_match.qty) >= Decimal(
                    "0.0001"
                ):
                    issues = list(o_line.issues)
                    conflict_msg = f"LINE_QTY_CONFLICT: Line {o_idx + 1} OCR={o_line.qty} vs Vision={v_match.qty}"
                    issues.append(conflict_msg)
                    if parser_issues is not None:
                        parser_issues.append(conflict_msg)
                    table_line_evidence.append(
                        FieldEvidence(
                            field_path=f"lines[{o_idx}].qty.candidate_vision",
                            source_kind="vision_llm",
                            raw_value=str(v_match.qty),
                            normalized_value=str(v_match.qty),
                            confidence=None,
                            extractor="openai_vision",
                            verification_state="model_proposed",
                            review_reason=f"Conflicting line quantity proposed by Vision AI ({v_match.qty}) against OCR ({o_line.qty})",
                        )
                    )
                    updated_sku = o_line.sku_ref or v_match.sku
                    o_line = o_line.model_copy(update={"sku_ref": updated_sku, "issues": issues})
                elif not o_line.sku_ref and v_match.sku:
                    o_line = o_line.model_copy(update={"sku_ref": v_match.sku})

            # Case 2: OCR quantity is truly missing/unrecovered (<= 0)
            else:
                has_unrecovered_qty = any(
                    iss
                    in (
                        "QTY_ZERO_OR_MISSING",
                        "QTY_UNRECOVERED",
                        "CELL_MERGE_SUSPECTED",
                    )
                    for iss in o_line.issues
                ) or o_line.qty <= Decimal("0.0000")

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
                                confidence=None,
                                extractor="openai_vision",
                                verification_state="arithmetically_consistent",
                                review_reason="Recovered missing quantity validated by arithmetic consistency",
                            )
                        )
                    else:
                        issues = list(o_line.issues)
                        mis_msg = f"VISION_QUANTITY_ARITHMETIC_MISMATCH: Vision={v_match.qty} * Price={o_line.unit_price} != Amt={o_line.line_amount}"
                        issues.append(mis_msg)
                        if parser_issues is not None:
                            parser_issues.append(mis_msg)
                        o_line = o_line.model_copy(update={"issues": issues})
                        table_line_evidence.append(
                            FieldEvidence(
                                field_path=f"lines[{o_idx}].qty.candidate_vision",
                                source_kind="vision_llm",
                                raw_value=str(v_match.qty),
                                normalized_value=str(v_match.qty),
                                confidence=None,
                                extractor="openai_vision",
                                verification_state="model_proposed",
                                review_reason="Vision quantity failed line arithmetic check",
                            )
                        )
                elif not o_line.sku_ref and v_match.sku:
                    o_line = o_line.model_copy(update={"sku_ref": v_match.sku})

            reconciled_lines.append(o_line)

        return reconciled_lines


def _vision_evidence(field_path: str, value: Any) -> FieldEvidence:
    # LLM self-reported confidence is not calibrated, so none is recorded.
    return FieldEvidence(
        field_path=field_path,
        source_kind="vision_llm",
        raw_value=str(value),
        normalized_value=str(value),
        extractor="openai_vision",
        verification_state="model_proposed",
    )


def vision_line_evidence(lines: list[InvoiceLine]) -> list[FieldEvidence]:
    return [
        _vision_evidence(f"lines[{index}].{name}", getattr(line, name))
        for index, line in enumerate(lines)
        for name in ("qty", "unit_price", "line_amount")
    ]


def _normalised_header_values(vision_res: Any, parser_issues: list[str]) -> Any:
    updates: dict[str, Any] = {}
    for name in ("supplier_tax_id", "buyer_tax_id"):
        value = getattr(vision_res, name, None)
        if value:
            updates[name] = normalize_tax_id(value)
    raw_date = getattr(vision_res, "issue_date", None)
    if raw_date:
        parsed = parse_printed_date(raw_date)
        if parsed is None:
            parser_issues.append(f"VISION_ISSUE_DATE_UNPARSEABLE: {raw_date}")
        updates["issue_date"] = parsed.isoformat() if parsed else None
    return vision_res.model_copy(update=updates) if updates else vision_res
