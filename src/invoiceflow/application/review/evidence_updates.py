"""Persist reviewer decisions on field evidence (one field and its Vision candidate)."""

from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.domain.invoices.evidence_gate import CANDIDATE_SUFFIX
from invoiceflow.domain.invoices.models import FieldVerificationState
from invoiceflow.infrastructure.database.models import FieldEvidenceORM

_APPROVED = FieldVerificationState.HUMAN_APPROVED.value
_REJECTED = FieldVerificationState.HUMAN_REJECTED.value


def same_value(left: Optional[str], right: Optional[str]) -> bool:
    if left is None or right is None:
        return left == right
    try:
        return Decimal(left) == Decimal(right)
    except InvalidOperation:
        return left.strip() == right.strip()


async def find_candidate(
    session: AsyncSession, invoice_id: str, field_path: str
) -> Optional[FieldEvidenceORM]:
    return (
        await session.execute(
            select(FieldEvidenceORM).where(
                FieldEvidenceORM.invoice_id == invoice_id,
                FieldEvidenceORM.field_path == f"{field_path}{CANDIDATE_SUFFIX}",
            )
        )
    ).scalar_one_or_none()


async def record_field_decision(
    session: AsyncSession,
    invoice_id: str,
    field_path: str,
    value: Optional[str],
    reason: str,
) -> None:
    """Mark the field human-approved with its final value and settle a competing candidate."""
    res = await session.execute(
        update(FieldEvidenceORM)
        .where(FieldEvidenceORM.invoice_id == invoice_id, FieldEvidenceORM.field_path == field_path)
        .values(verification_state=_APPROVED, normalized_value=value, review_reason=reason)
    )
    if res.rowcount == 0:
        session.add(
            FieldEvidenceORM(
                invoice_id=invoice_id,
                field_path=field_path,
                source_kind="human_review",
                normalized_value=value,
                extractor="human_review",
                verification_state=_APPROVED,
                review_reason=reason,
            )
        )
    candidate = await find_candidate(session, invoice_id, field_path)
    if candidate is not None:
        # The candidate was right only if the reviewer settled on its value.
        candidate.verification_state = (
            _APPROVED if same_value(candidate.normalized_value, value) else _REJECTED
        )
