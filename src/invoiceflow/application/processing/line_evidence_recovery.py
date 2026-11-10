"""Bounded, deterministic recovery of line-item evidence before any Vision fallback.

Two targeted steps, each accepting a value only when it is printed in the document and the
line arithmetic confirms it (same acceptance rule as region OCR retry):
- a quantity that table recognition fused into the end of the description cell;
- quantity / unit price of text (non-table) layouts, searched only inside the line's own
  block, which ends at the next line or at the invoice summary.
An unprinted line amount may be derived from grounded qty x price only when the printed
subtotal confirms the sum; it is marked as a derivation, never as located evidence.
"""

from decimal import Decimal
import re
from typing import Optional

from invoiceflow.domain.documents.models import CanonicalDocument, DocumentElement
from invoiceflow.domain.documents.value_parsing import fold_vietnamese, parse_vn_decimal
from invoiceflow.domain.invoices.evidence_gate import ARITHMETIC_DERIVATION
from invoiceflow.domain.invoices.field_labels import LINE_LABELS, TOTAL_LABELS
from invoiceflow.domain.invoices.models import FieldEvidence, FieldVerificationState, InvoiceLine

_ARITHMETIC_TOLERANCE = Decimal("0.0100")
_MERGE_ISSUES = frozenset(
    {"QTY_ZERO_OR_MISSING", "QTY_UNRECOVERED", "CELL_MERGE_SUSPECTED", "ARITHMETIC_MISMATCH"}
)
_TRAILING_NUMBER = re.compile(r"(\d[\d.,]*)\s*$")
_NUMBER = r"(\d[\d.,]*)(?![\w])"
_MAX_LINE_BLOCK = 4
_TOTAL_LABEL_SET = tuple(label for labels in TOTAL_LABELS.values() for label in labels)


def _reconciles(line: InvoiceLine, qty: Decimal) -> bool:
    expected = qty * line.unit_price - line.discount
    return abs(line.line_amount - expected) < _ARITHMETIC_TOLERANCE


def recover_merged_quantities(
    lines: list[InvoiceLine], evidence: list[FieldEvidence]
) -> tuple[list[InvoiceLine], list[FieldEvidence]]:
    descriptions = {ev.field_path: ev for ev in evidence if ev.field_path.endswith(".description")}
    recovered_lines: list[InvoiceLine] = []
    recovered_evidence = list(evidence)
    for index, line in enumerate(lines):
        source = descriptions.get(f"lines[{index}].description")
        split = _split_merged_quantity(line, source)
        if split is None or source is None:
            recovered_lines.append(line)
            continue
        qty, token = split
        description = line.description
        if description.endswith(token):
            description = description[: -len(token)].rstrip()
        recovered_lines.append(
            line.model_copy(
                update={
                    "qty": qty,
                    "raw_qty": token,
                    "description": description,
                    "issues": [issue for issue in line.issues if issue not in _MERGE_ISSUES],
                }
            )
        )
        recovered_evidence.append(
            source.model_copy(
                update={
                    "field_path": f"lines[{index}].qty",
                    "normalized_value": str(qty),
                    "confidence": None,
                    "extractor": "merged_cell_split",
                    "verification_state": FieldVerificationState.ARITHMETICALLY_CONSISTENT,
                    "review_reason": (
                        "Quantity printed at the end of a merged description cell; "
                        "confirmed by quantity x unit price = line amount"
                    ),
                }
            )
        )
    return recovered_lines, recovered_evidence


def _split_merged_quantity(
    line: InvoiceLine, source: Optional[FieldEvidence]
) -> Optional[tuple[Decimal, str]]:
    if not {"QTY_UNRECOVERED", "CELL_MERGE_SUSPECTED"} <= set(line.issues):
        return None
    if source is None or not source.raw_value:
        return None
    if line.unit_price <= 0 or line.line_amount <= 0:
        return None
    match = _TRAILING_NUMBER.search(source.raw_value)
    if match is None:
        return None
    token = match.group(1)
    qty, issue = parse_vn_decimal(token, is_qty=True)
    if issue is not None or qty <= 0 or not _reconciles(line, qty):
        return None
    return qty, token


def ground_text_lines(
    lines: list[InvoiceLine], doc: CanonicalDocument, subtotal_confirmed: bool
) -> list[FieldEvidence]:
    elements = list(doc.elements)
    folded = [fold_vietnamese(el.text) for el in elements]
    anchors = [_anchor_index(line, elements, folded) for line in lines]
    anchor_set = {anchor for anchor in anchors if anchor is not None}

    evidence: list[FieldEvidence] = []
    for index, (line, anchor) in enumerate(zip(lines, anchors)):
        if anchor is None:
            continue
        block = _line_block(anchor, folded, anchor_set)
        located = {}
        for name in ("qty", "unit_price", "line_amount"):
            element_index = _labelled_value(block, folded, name, getattr(line, name))
            if element_index is not None:
                located[name] = elements[element_index]
        evidence.extend(_located_evidence(index, line, located, doc))
        if (
            "line_amount" not in located
            and {"qty", "unit_price"} <= located.keys()
            and subtotal_confirmed
            and _reconciles(line, line.qty)
        ):
            evidence.append(_derived_line_amount(index, line))
    return evidence


def _anchor_index(
    line: InvoiceLine, elements: list[DocumentElement], folded: list[str]
) -> Optional[int]:
    description = fold_vietnamese(line.description)
    for index, element in enumerate(elements):
        if line.sku_ref and line.sku_ref in element.text:
            return index
        if len(description) >= 4 and description in folded[index]:
            return index
    return None


def _line_block(anchor: int, folded: list[str], anchors: set[int]) -> list[int]:
    block = [anchor]
    for index in range(anchor + 1, min(anchor + _MAX_LINE_BLOCK, len(folded))):
        if index in anchors or any(label in folded[index] for label in _TOTAL_LABEL_SET):
            break
        block.append(index)
    return block


def _labelled_value(
    block: list[int], folded: list[str], name: str, target: Decimal
) -> Optional[int]:
    labels = "|".join(re.escape(label) for label in LINE_LABELS[name])
    pattern = re.compile(rf"(?<![a-z])(?:{labels})\s*:?\s*{_NUMBER}")
    for index in block:
        for match in pattern.finditer(folded[index]):
            value, issue = parse_vn_decimal(match.group(1), is_qty=name == "qty")
            if issue is None and value == target:
                return index
    return None


def _located_evidence(
    index: int, line: InvoiceLine, located: dict[str, DocumentElement], doc: CanonicalDocument
) -> list[FieldEvidence]:
    return [
        FieldEvidence(
            field_path=f"lines[{index}].{name}",
            source_kind=doc.source_format,
            page_index=element.page_index,
            bbox=element.bbox,
            raw_value=element.text,
            normalized_value=str(getattr(line, name)),
            confidence=element.confidence,
            extractor=doc.parser_name,
            verification_state=FieldVerificationState.VALID,
        )
        for name, element in located.items()
    ]


def _derived_line_amount(index: int, line: InvoiceLine) -> FieldEvidence:
    return FieldEvidence(
        field_path=f"lines[{index}].line_amount",
        source_kind=ARITHMETIC_DERIVATION,
        normalized_value=str(line.line_amount),
        extractor="line_evidence_recovery",
        verification_state=FieldVerificationState.ARITHMETICALLY_CONSISTENT,
        review_reason=(
            "Line amount is not printed; equals grounded quantity x unit price - discount "
            "and the printed subtotal"
        ),
    )
