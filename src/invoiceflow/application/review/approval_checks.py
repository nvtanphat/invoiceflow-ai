"""Preconditions for human accounting approval of a reviewed invoice."""

from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.domain.invoices.evidence_gate import CANDIDATE_SUFFIX, manual_approval_blockers
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    FieldEvidenceORM,
    InvoiceLineORM,
    InvoiceORM,
    MatchResultORM,
)
from invoiceflow.infrastructure.database.repositories import PolicyRepository

_BLOCKING_MATCH_CODES = {
    "LINE_ARITHMETIC_MISMATCH",
    "TOTAL_PAYABLE_MISMATCH",
    "MISSING_SUPPLIER_TAX_ID",
    "MISSING_INVOICE_NUMBER",
    "ARITHMETIC_MISMATCH",
    "PARSE_ERROR",
    "AMBIGUOUS_NUMBER",
}


class ApprovalPreconditions:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def verify(self, invoice: InvoiceORM, actor_id: str, notes: Optional[str]) -> None:
        # Authorization first, then the most specific data defect, so the caller sees the cause.
        await self._assert_separation_of_duties(invoice, actor_id)
        await self._assert_line_arithmetic(invoice.id)
        await self._assert_evidence_resolved(invoice.id)
        await self._assert_match_allows_approval(invoice.tenant_id, invoice.id, notes)

    async def _assert_evidence_resolved(self, invoice_id: str) -> None:
        evidence = (
            (
                await self._session.execute(
                    select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == invoice_id)
                )
            )
            .scalars()
            .all()
        )
        unresolved_candidates = sorted(
            {
                ev.field_path
                for ev in evidence
                if ev.field_path.endswith(CANDIDATE_SUFFIX)
                and ev.verification_state == "model_proposed"
            }
        )
        if unresolved_candidates:
            raise ValueError(
                "Không thể phê duyệt: Hóa đơn còn xung đột tài chính chưa giải quyết "
                f"({', '.join(unresolved_candidates)}). Vui lòng xác minh hoặc chỉnh sửa trước khi duyệt."
            )
        blockers = manual_approval_blockers(
            ev for ev in evidence if not ev.field_path.endswith(CANDIDATE_SUFFIX)
        )
        if blockers:
            raise ValueError(
                f"UNRESOLVED_CRITICAL_FIELD: Không thể phê duyệt khi trường trọng yếu còn thiếu, "
                f"sai hoặc xung đột ({', '.join(blockers)}). Vui lòng đính chính trước khi duyệt."
            )

    async def _assert_line_arithmetic(self, invoice_id: str) -> None:
        lines = (
            (
                await self._session.execute(
                    select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
                )
            )
            .scalars()
            .all()
        )
        for line in lines:
            expected_amt = (line.qty * line.unit_price) - (line.discount or Decimal("0.0000"))
            if abs(line.line_amount - expected_amt) >= Decimal("0.0100"):
                raise ValueError(
                    f"Không thể phê duyệt: Hóa đơn có lỗi nghiêm trọng (LINE_ARITHMETIC_MISMATCH: Dòng {line.line_no} thành tiền {line.line_amount} != {expected_amt}). Vui lòng đính chính dữ liệu (correct) trước khi duyệt."
                )

    async def _assert_match_allows_approval(
        self, tenant_id: str, invoice_id: str, notes: Optional[str]
    ) -> None:
        match_res = (
            (
                await self._session.execute(
                    select(MatchResultORM)
                    .where(
                        MatchResultORM.tenant_id == tenant_id,
                        MatchResultORM.invoice_id == invoice_id,
                    )
                    .order_by(MatchResultORM.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if match_res is None:
            raise ValueError(
                "MATCH_REPORT_REQUIRED: Hóa đơn chưa được đối soát. Vui lòng chạy đối soát trước khi duyệt."
            )
        issues = json.loads(match_res.issues_json) if match_res.issues_json else []
        blocking_codes = sorted(
            {
                issue.get("code", "UNKNOWN")
                for issue in issues
                if issue.get("severity") == "critical"
                or issue.get("code") in _BLOCKING_MATCH_CODES
                or "CONFLICT" in (issue.get("code") or "")
            }
        )
        if blocking_codes:
            raise ValueError(
                f"Không thể phê duyệt: Hóa đơn có lỗi nghiêm trọng ({', '.join(blocking_codes)}). Vui lòng đính chính dữ liệu (correct) trước khi duyệt."
            )
        if match_res.requires_review and not match_res.is_matched and not (notes or "").strip():
            raise ValueError(
                "Hóa đơn có sai lệch đối soát (requires review). Cần ghi chú lý do phê duyệt (notes/override)."
            )

    async def _assert_separation_of_duties(self, invoice: InvoiceORM, actor_id: str) -> None:
        policy = await PolicyRepository(self._session).get_effective(
            invoice.tenant_id,
            invoice.supplier_tax_id,
            invoice.issue_date or datetime.now(timezone.utc).date(),
        )
        if not policy.separation_of_duties_required:
            return
        doc = await self._session.get(DocumentORM, invoice.document_id)
        if doc and doc.uploaded_by and doc.uploaded_by == actor_id:
            raise PermissionError(
                "Separation of duties violation: Document uploader cannot approve invoice."
            )
