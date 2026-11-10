"""Evidence rules that decide whether extracted invoice fields can be trusted.

Two consumers apply different strictness:
- straight-through processing needs every financially material field to be backed by
  deterministic source evidence (or a human decision);
- a human approver attests to UNCERTAIN/MODEL_PROPOSED values by approving, but may not
  approve over fields that are missing, invalid or conflicting.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, Union

from invoiceflow.domain.invoices.models import FieldVerificationState, InvoiceAggregate

CRITICAL_HEADER_FIELDS = (
    "supplier_tax_id",
    "supplier_name",
    "invoice_number",
    "issue_date",
    "subtotal",
    "tax_total",
    "amount_payable",
)
CRITICAL_LINE_FIELDS = ("qty", "unit_price", "line_amount")
CANDIDATE_SUFFIX = ".candidate_vision"
# Review reason of a value the parser produced but that could not be found in the document.
UNLOCATED_IN_SOURCE = "no_direct_text_match"

# Values a generative model produced cannot verify themselves, even when they add up.
MODEL_SOURCE_KINDS = frozenset({"vision_llm"})
# The verifier re-labels values it has no source evidence for; that is not provenance.
DERIVED_SOURCE_KINDS = frozenset({"multi_signal_verifier"})
# A line amount the document does not print, computed from grounded qty x price and
# reconciled to the printed subtotal. Acceptable for that field only.
ARITHMETIC_DERIVATION = "arithmetic_derivation"

_UNVERIFIED_STATES = frozenset(
    {
        FieldVerificationState.MISSING,
        FieldVerificationState.UNCERTAIN,
        FieldVerificationState.MODEL_PROPOSED,
    }
)
_MANUAL_BLOCKING_STATES = frozenset(
    {
        FieldVerificationState.MISSING,
        FieldVerificationState.INVALID,
        FieldVerificationState.CONFLICT,
    }
)
_NON_ZERO_TOTALS = frozenset({"amount_payable", "subtotal"})
_HUMAN_DECISIONS = frozenset(
    {FieldVerificationState.HUMAN_APPROVED, FieldVerificationState.HUMAN_REJECTED}
)


class EvidenceRecord(Protocol):
    field_path: str
    source_kind: str
    verification_state: Union[FieldVerificationState, str]
    normalized_value: Optional[str]


@dataclass(frozen=True)
class ReviewItem:
    """One field a reviewer must look at, with the values competing for it."""

    field_path: str
    reasons: list[str] = field(default_factory=list)
    current_value: Optional[str] = None
    source_kind: Optional[str] = None
    candidate_value: Optional[str] = None


def is_critical_field(field_path: str) -> bool:
    if field_path in CRITICAL_HEADER_FIELDS:
        return True
    if not field_path.startswith("lines[") or "]." not in field_path:
        return False
    return field_path.rsplit("].", 1)[1] in CRITICAL_LINE_FIELDS


def required_critical_paths(invoice: InvoiceAggregate) -> list[str]:
    return _required_paths(len(invoice.lines))


def _required_paths(line_count: int) -> list[str]:
    paths = list(CRITICAL_HEADER_FIELDS)
    for index in range(line_count):
        paths.extend(f"lines[{index}].{name}" for name in CRITICAL_LINE_FIELDS)
    return paths


def parse_state(record: EvidenceRecord) -> Optional[FieldVerificationState]:
    try:
        return FieldVerificationState(record.verification_state)
    except ValueError:
        return None


def automation_blockers(invoice: InvoiceAggregate) -> list[str]:
    """Reasons the extracted data is not verified enough for system approval."""
    if not invoice.evidence:
        return ["NO_FIELD_EVIDENCE"]

    blockers: list[str] = []
    for record in invoice.evidence:
        blockers.extend(_record_automation_blockers(record))

    present = {record.field_path for record in invoice.evidence}
    blockers.extend(
        f"MISSING_FIELD_EVIDENCE: {path}"
        for path in required_critical_paths(invoice)
        if path not in present
    )
    return blockers


def _record_automation_blockers(record: EvidenceRecord) -> list[str]:
    path = record.field_path
    state = parse_state(record)
    if state is None:
        return [f"UNKNOWN_VERIFICATION_STATE: {path}"]
    if state in _HUMAN_DECISIONS:
        return []
    if state == FieldVerificationState.CONFLICT:
        return [f"FIELD_CONFLICT: {path}"]
    if state == FieldVerificationState.INVALID:
        return [f"FIELD_INVALID: {path}"]
    if path.endswith(CANDIDATE_SUFFIX):
        return [f"UNRESOLVED_VISION_CANDIDATE: {path}"]
    if not is_critical_field(path):
        return []
    return _critical_record_blockers(record, state)


def _critical_record_blockers(record: EvidenceRecord, state: FieldVerificationState) -> list[str]:
    path = record.field_path
    if state in _UNVERIFIED_STATES:
        return [f"UNVERIFIED_CRITICAL_FIELD: {path} ({state.value})"]
    if state == FieldVerificationState.ZERO and path in _NON_ZERO_TOTALS:
        return [f"ZERO_FINANCIAL_TOTAL: {path}"]
    derived_line_amount = record.source_kind == ARITHMETIC_DERIVATION and path.endswith(
        ".line_amount"
    )
    if record.source_kind in DERIVED_SOURCE_KINDS or (
        record.source_kind == ARITHMETIC_DERIVATION and not derived_line_amount
    ):
        return [f"DERIVED_EVIDENCE_ONLY: {path}"]
    if record.source_kind in MODEL_SOURCE_KINDS:
        if state == FieldVerificationState.ARITHMETICALLY_CONSISTENT:
            return [f"VISION_ONLY_ARITHMETIC_EVIDENCE: {path}"]
        return [f"MODEL_SOURCED_CRITICAL_FIELD: {path}"]
    return []


def manual_approval_blockers(records: Iterable[EvidenceRecord]) -> list[str]:
    """Critical fields a human must correct (not merely approve) before accounting approval."""
    blockers = []
    for record in records:
        if not is_critical_field(record.field_path):
            continue
        state = parse_state(record)
        if state is None or state in _MANUAL_BLOCKING_STATES:
            label = state.value if state else str(record.verification_state)
            blockers.append(f"{record.field_path} ({label})")
    return sorted(blockers)


def review_items(records: Iterable[EvidenceRecord], line_count: int) -> list[ReviewItem]:
    """Fields still needing a human decision; everything else is settled by evidence."""
    by_path = {record.field_path: record for record in records}
    candidates = {
        path[: -len(CANDIDATE_SUFFIX)]: record
        for path, record in by_path.items()
        if path.endswith(CANDIDATE_SUFFIX) and parse_state(record) not in _HUMAN_DECISIONS
    }
    required = _required_paths(line_count)
    ordered = required + [
        path for path in by_path if path not in required and not path.endswith(CANDIDATE_SUFFIX)
    ]

    items = []
    for path in ordered:
        record = by_path.get(path)
        reasons = (
            ["MISSING_FIELD_EVIDENCE"] if record is None else _record_automation_blockers(record)
        )
        candidate = candidates.get(path)
        if candidate is not None:
            reasons.append(f"UNRESOLVED_VISION_CANDIDATE: {path}{CANDIDATE_SUFFIX}")
        if reasons:
            items.append(
                ReviewItem(
                    field_path=path,
                    reasons=reasons,
                    current_value=record.normalized_value if record else None,
                    source_kind=record.source_kind if record else None,
                    candidate_value=candidate.normalized_value if candidate else None,
                )
            )
    return items
