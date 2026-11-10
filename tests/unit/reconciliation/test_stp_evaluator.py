from datetime import date
from decimal import Decimal
import uuid

from invoiceflow.application.reconciliation.stp_evaluator import STPEvaluator
from invoiceflow.domain.invoices.evidence_gate import required_critical_paths
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


def _source_evidence(invoice: InvoiceAggregate) -> list[FieldEvidence]:
    """Deterministic XML evidence for every critical field, as the XML parser emits it."""
    return [
        FieldEvidence(
            field_path=path,
            source_kind="xml",
            extractor="xml_deterministic",
            raw_value="source",
            verification_state=FieldVerificationState.VALID,
        )
        for path in required_critical_paths(invoice)
    ]


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
        issue_date=date(2026, 11, 8),
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

    inv.evidence = _source_evidence(inv)
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
        auto_approval_enabled=True,
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
        issue_date=date(2026, 11, 8),
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

    inv.evidence = _source_evidence(inv)
    policy = TolerancePolicy(tenant_id=tenant_id, auto_approval_enabled=True)
    res = evaluator.evaluate(invoice=inv, match_report=match_report, policy=policy)

    assert res.is_stp_eligible is True
    assert res.target_status == InvoiceStatus.APPROVED
    assert "3_WAY_MATCH_WITHIN_TOLERANCE" in res.stp_reasons


def _eligible_invoice_and_match():
    tenant_id = uuid.uuid4()
    invoice = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        supplier_name="Verified supplier",
        invoice_number="INV-SECURE",
        issue_date=date(2026, 11, 8),
        subtotal=Decimal("2000000.0000"),
        amount_payable=Decimal("2000000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Equipment",
                qty=Decimal("2.0000"),
                unit_price=Decimal("1000000.0000"),
                line_amount=Decimal("2000000.0000"),
            )
        ],
    )
    invoice.evidence = _source_evidence(invoice)
    matched = MatchReport(
        invoice_id=invoice.id,
        status=MatchStatus.MATCHED_EXACT,
        is_matched=True,
        requires_review=False,
        issues=[],
    )
    policy = TolerancePolicy(
        tenant_id=tenant_id,
        auto_approval_enabled=True,
    )
    return invoice, matched, policy


def test_stp_default_policy_never_auto_approves():
    invoice, matched, _ = _eligible_invoice_and_match()

    result = STPEvaluator().evaluate(invoice, matched, TolerancePolicy(tenant_id=invoice.tenant_id))

    assert result.extraction_verified is True
    assert result.matching_cleared is True
    assert result.accounting_approved is False
    assert not result.is_stp_eligible
    assert result.target_status == InvoiceStatus.READY_FOR_REVIEW
    assert "AUTO_APPROVAL_DISABLED_BY_POLICY" in result.review_reasons


def test_stp_separation_of_duties_flag_does_not_replace_auto_approval_policy():
    invoice, matched, policy = _eligible_invoice_and_match()
    policy.separation_of_duties_required = True

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert result.accounting_approved is True
    assert result.target_status == InvoiceStatus.APPROVED


def test_stp_reports_each_gate_independently():
    invoice, matched, policy = _eligible_invoice_and_match()
    matched.status = MatchStatus.PRICE_VARIANCE
    matched.is_matched = False
    matched.requires_review = True

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert result.extraction_verified is True
    assert result.matching_cleared is False
    assert result.accounting_approved is False
    assert result.target_status == InvoiceStatus.READY_FOR_REVIEW


def test_stp_missing_po_blocks_when_policy_requires_po():
    invoice, _, policy = _eligible_invoice_and_match()
    missing_po = MatchReport(
        invoice_id=invoice.id,
        status=MatchStatus.MISSING_PO,
        is_matched=False,
        requires_review=True,
        issues=[MatchIssue(code="MISSING_PO", message="No PO")],
    )

    result = STPEvaluator().evaluate(invoice, missing_po, policy)

    assert result.matching_cleared is False
    assert "MISSING_PURCHASE_ORDER" in result.review_reasons


def test_stp_non_po_invoice_clears_matching_only_when_policy_allows():
    invoice, _, policy = _eligible_invoice_and_match()
    policy.po_required = False
    missing_po = MatchReport(
        invoice_id=invoice.id,
        status=MatchStatus.MISSING_PO,
        is_matched=False,
        requires_review=True,
        issues=[MatchIssue(code="MISSING_PO", message="No PO")],
    )

    result = STPEvaluator().evaluate(invoice, missing_po, policy)

    assert result.matching_cleared is True
    assert "NON_PO_INVOICE_ALLOWED_BY_POLICY" in result.stp_reasons
    assert result.accounting_approved is True


def test_stp_non_po_invoice_with_validation_issues_is_not_cleared():
    invoice, _, policy = _eligible_invoice_and_match()
    policy.po_required = False
    missing_po = MatchReport(
        invoice_id=invoice.id,
        status=MatchStatus.MISSING_PO,
        is_matched=False,
        requires_review=True,
        issues=[
            MatchIssue(code="MISSING_PO", message="No PO"),
            MatchIssue(code="DUPLICATE_INVOICE", message="Duplicate"),
        ],
    )

    result = STPEvaluator().evaluate(invoice, missing_po, policy)

    assert result.matching_cleared is False


def test_stp_blocks_vision_sourced_critical_fields_even_when_marked_valid():
    invoice, matched, policy = _eligible_invoice_and_match()
    for field_path in ("lines[0].unit_price", "tax_total"):
        invoice.evidence = [
            FieldEvidence(
                field_path=field_path,
                source_kind="vision_llm",
                verification_state=FieldVerificationState.VALID,
            )
        ]

        result = STPEvaluator().evaluate(invoice, matched, policy)

        assert result.extraction_verified is False
        assert any("MODEL_SOURCED_CRITICAL_FIELD" in r for r in result.review_reasons)


def test_stp_accepts_vision_sourced_field_after_human_approval():
    invoice, matched, policy = _eligible_invoice_and_match()
    invoice.evidence.append(
        FieldEvidence(
            field_path="tax_total",
            source_kind="vision_llm",
            verification_state=FieldVerificationState.HUMAN_APPROVED,
        )
    )

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert result.extraction_verified is True


def test_stp_requires_a_completed_matching_report():
    invoice, _, policy = _eligible_invoice_and_match()

    result = STPEvaluator().evaluate(invoice, match_report=None, policy=policy)

    assert not result.is_stp_eligible
    assert "MATCH_REPORT_REQUIRED" in result.review_reasons


def test_stp_blocks_matching_flagged_for_review():
    invoice, matched, policy = _eligible_invoice_and_match()
    matched.requires_review = True

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert not result.is_stp_eligible
    assert "MATCH_REPORT_NOT_CLEARED" in result.review_reasons


def test_stp_blocks_unverified_critical_fields():
    invoice, matched, policy = _eligible_invoice_and_match()
    for state in (
        FieldVerificationState.MISSING,
        FieldVerificationState.UNCERTAIN,
        FieldVerificationState.MODEL_PROPOSED,
    ):
        invoice.evidence = [
            FieldEvidence(
                field_path="amount_payable",
                source_kind="vision_llm",
                verification_state=state,
            )
        ]
        result = STPEvaluator().evaluate(invoice, matched, policy)
        assert not result.is_stp_eligible
        assert any("UNVERIFIED_CRITICAL_FIELD" in reason for reason in result.review_reasons)


def test_stp_blocks_vision_only_arithmetic_and_candidate_evidence():
    invoice, matched, policy = _eligible_invoice_and_match()
    invoice.evidence = [
        FieldEvidence(
            field_path="lines[0].qty",
            source_kind="vision_llm",
            verification_state=FieldVerificationState.ARITHMETICALLY_CONSISTENT,
        ),
        FieldEvidence(
            field_path="lines[0].qty.candidate_vision",
            source_kind="vision_llm",
            verification_state=FieldVerificationState.MODEL_PROPOSED,
        ),
    ]

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert not result.is_stp_eligible
    assert any("VISION_ONLY_ARITHMETIC_EVIDENCE" in r for r in result.review_reasons)
    assert any("UNRESOLVED_VISION_CANDIDATE" in r for r in result.review_reasons)


def test_stp_blocks_unresolved_parser_issues():
    invoice, matched, policy = _eligible_invoice_and_match()
    invoice.parser_issues = ["QTY_UNRECOVERED"]

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert not result.is_stp_eligible
    assert "UNRESOLVED_PARSER_ISSUES" in result.review_reasons


def test_stp_blocks_missing_evidence_and_line_items():
    invoice, matched, policy = _eligible_invoice_and_match()
    invoice.evidence = []
    invoice.lines = []

    result = STPEvaluator().evaluate(invoice, matched, policy)

    assert not result.is_stp_eligible
    assert "NO_FIELD_EVIDENCE" in result.review_reasons
    assert "MISSING_LINE_ITEMS" in result.review_reasons


def test_arithmetic_derivation_is_accepted_only_for_unprinted_line_amounts():
    invoice, matched, policy = _eligible_invoice_and_match()
    for ev in invoice.evidence:
        if ev.field_path in ("lines[0].line_amount", "lines[0].qty"):
            ev.source_kind = "arithmetic_derivation"
            ev.verification_state = FieldVerificationState.ARITHMETICALLY_CONSISTENT

    reasons = STPEvaluator().evaluate(invoice, matched, policy).review_reasons

    assert "DERIVED_EVIDENCE_ONLY: lines[0].qty" in reasons
    assert not any("lines[0].line_amount" in r for r in reasons)
