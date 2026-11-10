"""Grounds extracted field values in the canonical document (element/cell text + bbox).

Values are matched by meaning, not by string: money by Decimal value across VN/US
notations, dates across common printed formats, text accent-insensitively. When a value
appears several times (a single-line invoice's subtotal equals its line amount), the
element carrying the field's label wins. A value that cannot be found is recorded as
UNCERTAIN without bbox; it is never presented as located source evidence.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Callable, List, Optional

from invoiceflow.domain.documents.models import BoundingBox, CanonicalDocument
from invoiceflow.domain.documents.value_parsing import fold_vietnamese, parse_vn_decimal
from invoiceflow.domain.invoices.evidence_gate import AMBIGUOUS_DATE_ORDER, UNLOCATED_IN_SOURCE
from invoiceflow.domain.invoices.field_labels import TOTAL_LABELS
from invoiceflow.domain.invoices.models import FieldEvidence, FieldVerificationState

_MONEY_FIELDS = frozenset({"subtotal", "tax_total", "amount_payable", "discount_total"})
_DATE_FIELDS = frozenset({"issue_date"})
_VN_DATE_LABEL = re.compile(r"\bngay\b")
_NUMBER_TOKENS = (re.compile(r"\d[\d.,]*\d|\d"), re.compile(r"\d{1,3}(?:\s\d{3})+"))
_MIN_FUZZY_TEXT_LENGTH = 4


@dataclass(frozen=True)
class _SourceText:
    text: str
    folded: str
    bbox: Optional[BoundingBox]
    page_index: Optional[int]
    confidence: Optional[float]
    table_id: Optional[str] = None
    cell_id: Optional[str] = None


class EvidenceMapper:
    def map_evidence(
        self,
        extracted_fields: dict[str, Any],
        canonical_doc: CanonicalDocument,
    ) -> List[FieldEvidence]:
        sources = _source_texts(canonical_doc)
        evidence_list: List[FieldEvidence] = []
        for field_path, value in extracted_fields.items():
            if value is None or not str(value).strip():
                continue
            str_val = str(value).strip()
            matches = [src for src in sources if _matcher(field_path, str_val)(src)]
            if field_path in _DATE_FIELDS:
                evidence_list.append(_date_evidence(field_path, str_val, matches, canonical_doc))
                continue
            located = _prefer_labelled(field_path, matches)
            evidence_list.append(_evidence(field_path, str_val, located, canonical_doc))
        return evidence_list


def _source_texts(doc: CanonicalDocument) -> list[_SourceText]:
    sources = [
        _SourceText(
            text=el.text,
            folded=fold_vietnamese(el.text),
            bbox=el.bbox,
            page_index=el.page_index,
            confidence=el.confidence,
        )
        for el in doc.elements
    ]
    for table in doc.tables:
        sources.extend(
            _SourceText(
                text=cell.text,
                folded=fold_vietnamese(cell.text),
                bbox=cell.bbox,
                page_index=cell.bbox.page_index if cell.bbox else table.page_index,
                confidence=None,
                table_id=table.id,
                cell_id=cell.id,
            )
            for cell in table.cells
        )
    return sources


def _matcher(field_path: str, value: str) -> Callable[[_SourceText], bool]:
    if field_path in _MONEY_FIELDS:
        try:
            target = Decimal(value)
        except InvalidOperation:
            return _text_matcher(value)
        return lambda src: target in _numbers_in(src.text)
    if field_path in _DATE_FIELDS:
        try:
            pattern = _date_pattern(date.fromisoformat(value))
        except ValueError:
            return _text_matcher(value)
        return lambda src: pattern.search(src.folded) is not None
    return _text_matcher(value)


def _text_matcher(value: str) -> Callable[[_SourceText], bool]:
    folded = fold_vietnamese(value)
    if len(value) < _MIN_FUZZY_TEXT_LENGTH:
        return lambda src: value in src.text
    return lambda src: value in src.text or folded in src.folded


def _numbers_in(text: str) -> set[Decimal]:
    values = set()
    for pattern in _NUMBER_TOKENS:
        for token in pattern.findall(text):
            parsed, issue = parse_vn_decimal(token)
            if issue is None:
                values.add(parsed)
    return values


def _date_pattern(value: date) -> re.Pattern[str]:
    day, month, year = rf"0?{value.day}", rf"0?{value.month}", str(value.year)
    return re.compile(
        rf"(?<!\d)(?:{value.isoformat()}"
        rf"|{day}\s*[/.-]\s*{month}\s*[/.-]\s*{year}"
        rf"|ngay\s*{day}\s*thang\s*{month}\s*nam\s*{year})(?!\d)"
    )


def _date_order_is_grounded(src: _SourceText, value: date) -> bool:
    """True when the located text fixes which number is the day.

    ISO and worded ("ngay d thang m nam y") renderings are unambiguous, as is any date whose
    day exceeds 12 or equals the month. A Vietnamese date label states the day/month
    convention of Vietnamese invoices; an unlabelled or foreign numeric date does not.
    """
    if value.day > 12 or value.day == value.month:
        return True
    unambiguous = re.compile(
        rf"{value.isoformat()}|ngay\s*0?{value.day}\s*thang\s*0?{value.month}\s*nam\s*{value.year}"
    )
    return bool(unambiguous.search(src.folded)) or _VN_DATE_LABEL.search(src.folded) is not None


def _date_evidence(
    field_path: str, value: str, matches: list[_SourceText], doc: CanonicalDocument
) -> FieldEvidence:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return _evidence(field_path, value, matches[0] if matches else None, doc)
    grounded = [src for src in matches if _date_order_is_grounded(src, parsed)]
    located = grounded[0] if grounded else (matches[0] if matches else None)
    evidence = _evidence(field_path, value, located, doc)
    if located is not None and not grounded:
        return evidence.model_copy(
            update={
                "verification_state": FieldVerificationState.UNCERTAIN,
                "review_reason": AMBIGUOUS_DATE_ORDER,
            }
        )
    return evidence


def _prefer_labelled(field_path: str, matches: list[_SourceText]) -> Optional[_SourceText]:
    labels = TOTAL_LABELS.get(field_path, ())
    for src in matches:
        if any(label in src.folded for label in labels):
            return src
    return matches[0] if matches else None


def _evidence(
    field_path: str, value: str, src: Optional[_SourceText], doc: CanonicalDocument
) -> FieldEvidence:
    if src is None:
        return FieldEvidence(
            field_path=field_path,
            source_kind=doc.source_format,
            normalized_value=value,
            extractor=doc.parser_name,
            verification_state=FieldVerificationState.UNCERTAIN,
            review_reason=UNLOCATED_IN_SOURCE,
        )
    return FieldEvidence(
        field_path=field_path,
        source_kind=doc.source_format,
        page_index=src.page_index,
        bbox=src.bbox,
        table_id=src.table_id,
        cell_id=src.cell_id,
        raw_value=src.text,
        normalized_value=value,
        confidence=src.confidence,
        extractor=doc.parser_name,
        verification_state=FieldVerificationState.VALID,
    )
