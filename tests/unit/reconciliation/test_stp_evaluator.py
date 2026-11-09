from decimal import Decimal
import uuid

from invoiceflow.application.reconciliation.stp_evaluator import STPEvaluator
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    FieldVerificationState,
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
)
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import (
    IssueSeverity,
    MatchIssue,
    MatchReport,
    MatchStatus,
)


def test_stp_evaluator_approves_clean_exact_match_below_threshold():
    evaluator = STPEvaluator()
    tenant_id = uuid.uuid4()

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        supplier_name="Công ty TNHH Chuẩn",
        invoice_number="INV-001",
        subtotal=Decimal("5000000.0000"),
        tax_total=Decimal("500000.0000"),
        amount_payable=Decimal("5500000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Hàng hóa A",
                qty=Decimal("10.0000"),
                unit_price=Decimal("500000.0000"),
                line_amount=Decimal("5000000.0000"),
            )
        ],
        evidence=[
            FieldEvidence(
                field_path="supplier_tax_id",
                source_kind="xml",
                raw_value="0101234567",
                normalized_value="0101234567",
                verification_state=FieldVerificationState.VALID,
            )
        ],
    )

    match_report = MatchReport(
        invoice_id=inv.id,
        status=MatchStatus.MATCHED_EXACT,
        is_matched=True,
        requires_review=False,
        issues=[],
    )

    policy = TolerancePolicy(
        tenant_id=tenant_id,
        auto_approve_threshold=Decimal("10000000.0000"),
    )

    res = evaluator.evaluate(invoice=inv, match_report=match_report, policy=policy)
    assert res.is_stp_eligible is True
    assert res.target_status == InvoiceStatus.APPROVED
    assert "3_WAY_MATCH_EXACT" in res.stp_reasons
    assert "BELOW_AUTO_APPROVE_THRESHOLD" in res.stp_reasons
    assert not res.review_reasons


def test_stp_evaluator_routes_to_review_when_amount_exceeds_threshold():
    evaluator = STPEvaluator()
    tenant_id = uuid.uuid4()

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-002",
        subtotal=Decimal("15000000.0000"),
        tax_total=Decimal("0.0000"),
        amount_payable=Decimal("15000000.0000"),  # Exceeds 10M threshold
        lines=[
            InvoiceLine(
                line_no=1,
                description="Server máy chủ",
                qty=Decimal("1.0000"),
                unit_price=Decimal("15000000.0000"),
                line_amount=Decimal("15000000.0000"),
            )
        ],
    )

    match_report = MatchReport(
        invoice_id=inv.id,
        status=MatchStatus.MATCHED_EXACT,
        is_matched=True,
        requires_review=False,
        issues=[],
    )

    policy = TolerancePolicy(
        tenant_id=tenant_id,
        auto_approve_threshold=Decimal("10000000.0000"),
    )

    res = evaluator.evaluate(invoice=inv, match_report=match_report, policy=policy)
    assert res.is_stp_eligible is False
    assert res.target_status == InvoiceStatus.READY_FOR_REVIEW
    assert any("AMOUNT_EXCEEDS_THRESHOLD" in r for r in res.review_reasons)


def test_stp_evaluator_routes_to_review_when_critical_issue_exists():
    evaluator = STPEvaluator()
    tenant_id = uuid.uuid4()

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-003",
        subtotal=Decimal("2000000.0000"),
        tax_total=Decimal("0.0000"),
        amount_payable=Decimal("2000000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Bàn làm việc",
                qty=Decimal("2.0000"),
                unit_price=Decimal("1000000.0000"),
                line_amount=Decimal("2000000.0000"),
            )
        ],
    )

    match_report = MatchReport(
        invoice_id=inv.id,
        status=MatchStatus.EXCEPTION,
        is_matched=False,
        requires_review=True,
        issues=[
            MatchIssue(
                code="INVALID_SUPPLIER_TAX_ID",
                severity=IssueSeverity.CRITICAL,
                message="MST sai định dạng",
            )
        ],
    )

    policy = TolerancePolicy(tenant_id=tenant_id)
    res = evaluator.evaluate(invoice=inv, match_report=match_report, policy=policy)

    assert res.is_stp_eligible is False
    assert res.target_status == InvoiceStatus.READY_FOR_REVIEW
    assert any("CRITICAL_ISSUE_INVALID_SUPPLIER_TAX_ID" in r for r in res.review_reasons)


def test_stp_evaluator_routes_to_review_when_candidate_conflict_exists():
    evaluator = STPEvaluator()
    tenant_id = uuid.uuid4()

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-004",
        subtotal=Decimal("2000000.0000"),
        tax_total=Decimal("0.0000"),
        amount_payable=Decimal("2000000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Ghế văn phòng",
                qty=Decimal("2.0000"),
                unit_price=Decimal("1000000.0000"),
                line_amount=Decimal("2000000.0000"),
            )
        ],
        evidence=[
            FieldEvidence(
                field_path="supplier_tax_id.candidate_vision",
                source_kind="vision_llm",
                raw_value="0109999999",
                normalized_value="0109999999",
                verification_state=FieldVerificationState.CONFLICT,
                review_reason="Vision conflicting tax ID",
            )
        ],
    )

    match_report = MatchReport(
        invoice_id=inv.id,
        status=MatchStatus.MATCHED_EXACT,
        is_matched=True,
        requires_review=False,
        issues=[],
    )

    policy = TolerancePolicy(tenant_id=tenant_id)
    res = evaluator.evaluate(invoice=inv, match_report=match_report, policy=policy)

    assert res.is_stp_eligible is False
    assert res.target_status == InvoiceStatus.READY_FOR_REVIEW
    assert any("FIELD_CONFLICT" in r for r in res.review_reasons)


def test_stp_evaluator_approves_within_tolerance_match():
    evaluator = STPEvaluator()
    tenant_id = uuid.uuid4()

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-005",
        subtotal=Decimal("1010000.0000"),
        tax_total=Decimal("0.0000"),
        amount_payable=Decimal("1010000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Vật tư",
                qty=Decimal("10.0000"),
                unit_price=Decimal("101000.0000"),
                line_amount=Decimal("1010000.0000"),
            )
        ],
    )

    match_report = MatchReport(
        invoice_id=inv.id,
        status=MatchStatus.MATCHED_WITHIN_TOLERANCE,
        is_matched=True,
        requires_review=False,
        issues=[],
    )

    policy = TolerancePolicy(tenant_id=tenant_id)
    res = evaluator.evaluate(invoice=inv, match_report=match_report, policy=policy)

    assert res.is_stp_eligible is True
    assert res.target_status == InvoiceStatus.APPROVED
    assert "3_WAY_MATCH_WITHIN_TOLERANCE" in res.stp_reasons
