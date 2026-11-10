from datetime import date
from decimal import Decimal
import uuid

from invoiceflow.application.processing.multi_signal_verifier import MultiSignalVerifier
from invoiceflow.application.reconciliation.matching_engine import MatchingEngine
from invoiceflow.application.reconciliation.validator import InvoiceValidator
from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    FieldVerificationState,
    InvoiceAggregate,
    InvoiceLine,
    TaxBreakdown,
)
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import (
    MatchStatus,
    POLine,
    PurchaseOrder,
)


def test_multi_signal_verifier_assigns_correct_states():
    verifier = MultiSignalVerifier()

    # Invoice with arithmetic consistency, missing buyer tax id, and conflict evidence
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        supplier_name="Công ty TNHH Thăng Long",
        buyer_tax_id=None,  # Missing
        invoice_number="0001234",
        subtotal=Decimal("50000000.0000"),
        tax_total=Decimal("5000000.0000"),
        amount_payable=Decimal("55000000.0000"),  # 50M + 5M = 55M (arithmetically consistent)
        lines=[
            InvoiceLine(
                line_no=1,
                description="Laptop Dell XPS",
                qty=Decimal("2.0000"),
                unit_price=Decimal("25000000.0000"),
                line_amount=Decimal("50000000.0000"),  # 2 * 25M = 50M (arithmetically consistent)
            )
        ],
        evidence=[
            FieldEvidence(
                field_path="supplier_tax_id",
                source_kind="docling_table",
                raw_value="0101234567",
                normalized_value="0101234567",
                confidence=0.95,
            ),
            FieldEvidence(
                field_path="supplier_tax_id.candidate_vision",
                source_kind="vision_llm",
                raw_value="0109999999",
                normalized_value="0109999999",
                confidence=0.75,
            ),
        ],
        parser_issues=["FIELD_CONFLICT_SUPPLIER_TAX_ID: OCR=0101234567 vs Vision=0109999999"],
    )

    verified = verifier.verify_invoice(inv)
    ev_map = {ev.field_path: ev for ev in verified.evidence}

    # Supplier tax id has conflict
    assert ev_map["supplier_tax_id"].verification_state == FieldVerificationState.CONFLICT

    # Buyer tax id is missing
    assert ev_map["buyer_tax_id"].verification_state == FieldVerificationState.MISSING

    # Amount payable and line amount are arithmetically consistent
    assert (
        ev_map["amount_payable"].verification_state
        == FieldVerificationState.ARITHMETICALLY_CONSISTENT
    )
    assert (
        ev_map["lines[0].line_amount"].verification_state
        == FieldVerificationState.ARITHMETICALLY_CONSISTENT
    )


def test_validator_detects_invalid_vietnamese_tax_id():
    validator = InvoiceValidator()

    # Invalid tax ID (only 8 digits instead of 10 or 13)
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="12345678",  # Invalid
        invoice_number="INV-001",
        amount_payable=Decimal("1000000.0000"),
    )

    issues = validator.validate(inv)
    codes = [i.code for i in issues]
    assert "INVALID_SUPPLIER_TAX_ID" in codes


def test_validator_detects_invalid_vietnamese_vat_rate():
    validator = InvoiceValidator()

    # Non-standard VAT rate in Vietnam (e.g. 15%)
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-001",
        subtotal=Decimal("1000000.0000"),
        tax_total=Decimal("150000.0000"),
        amount_payable=Decimal("1150000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Hàng chịu thuế lạ",
                qty=Decimal("1.0000"),
                unit_price=Decimal("1000000.0000"),
                line_amount=Decimal("1000000.0000"),
                tax_rate=Decimal("15.0000"),  # Invalid statutory rate
                tax=Decimal("150000.0000"),
            )
        ],
    )

    issues = validator.validate(inv)
    codes = [i.code for i in issues]
    assert "INVALID_VAT_RATE" in codes


def test_validator_detects_tax_breakdown_mismatch():
    validator = InvoiceValidator()

    # Tax breakdown sum does not match invoice tax total
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-001",
        subtotal=Decimal("1000000.0000"),
        tax_total=Decimal("100000.0000"),  # Total 100k
        amount_payable=Decimal("1100000.0000"),
        tax_breakdown=[
            TaxBreakdown(
                tax_rate=Decimal("10.0000"),
                taxable_amount=Decimal("1000000.0000"),
                tax_amount=Decimal("80000.0000"),  # Breakdown says 80k != 100k
            )
        ],
    )

    issues = validator.validate(inv)
    codes = [i.code for i in issues]
    assert "TAX_BREAKDOWN_MISMATCH" in codes


def test_validator_detects_duplicate_invoice():
    validator = InvoiceValidator()
    tenant_id = uuid.uuid4()

    inv1 = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="0004567",
        invoice_series="1C26TAA",
        amount_payable=Decimal("1000000.0000"),
    )

    inv2 = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="0004567",
        invoice_series="1C26TAA",
        amount_payable=Decimal("1000000.0000"),
    )

    issues = validator.check_duplicates(inv2, [inv1])
    assert any(i.code == "DUPLICATE_INVOICE" for i in issues)


def test_matching_engine_detects_uom_mismatch():
    engine = MatchingEngine()
    tenant_id = uuid.uuid4()
    po_id = uuid.uuid4()
    po_line_id = uuid.uuid4()

    po = PurchaseOrder(
        id=po_id,
        tenant_id=tenant_id,
        vendor_tax_id="0101234567",
        vendor_name="Nhà cung cấp",
        po_number="PO-100",
        order_date=date(2026, 11, 1),
        subtotal=Decimal("5000000.0000"),
        lines=[
            POLine(
                id=po_line_id,
                po_id=po_id,
                line_no=1,
                sku="SKU-PAPER",
                description="Giấy in A4",
                unit="thùng",  # PO in boxes/cartons
                ordered_qty=Decimal("10.0000"),
                unit_price=Decimal("500000.0000"),
                line_total=Decimal("5000000.0000"),
            )
        ],
    )

    inv = InvoiceAggregate(
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-100",
        subtotal=Decimal("5000000.0000"),
        amount_payable=Decimal("5000000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                sku_ref="SKU-PAPER",
                description="Giấy in A4",
                unit="ram",  # Invoice in reams -> UoM Mismatch!
                qty=Decimal("10.0000"),
                unit_price=Decimal("500000.0000"),
                line_amount=Decimal("5000000.0000"),
                purchase_order_line_id=po_line_id,
            )
        ],
    )

    report = engine.match_3_way(invoice=inv, po=po)
    codes = [i.code for i in report.issues]
    assert "UOM_MISMATCH" in codes


def test_matching_engine_matched_within_tolerance():
    engine = MatchingEngine()
    tenant_id = uuid.uuid4()
    po_id = uuid.uuid4()
    po_line_id = uuid.uuid4()

    # PO price: 100,000 VND
    po = PurchaseOrder(
        id=po_id,
        tenant_id=tenant_id,
        vendor_tax_id="0101234567",
        vendor_name="Nhà cung cấp",
        po_number="PO-200",
        order_date=date(2026, 11, 1),
        subtotal=Decimal("1000000.0000"),
        lines=[
            POLine(
                id=po_line_id,
                po_id=po_id,
                line_no=1,
                sku="SKU-TOOL",
                description="Bộ cờ lê đa năng",
                unit="bộ",
                ordered_qty=Decimal("10.0000"),
                unit_price=Decimal("100000.0000"),
                line_total=Decimal("1000000.0000"),
            )
        ],
    )

    # Invoice price: 101,000 VND (1% difference, within 2% tolerance)
    inv = InvoiceAggregate(
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-200",
        subtotal=Decimal("1010000.0000"),
        amount_payable=Decimal("1010000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                sku_ref="SKU-TOOL",
                description="Bộ cờ lê đa năng",
                unit="set",  # "set" == "bo" (synonym, normalized)
                qty=Decimal("10.0000"),
                unit_price=Decimal("101000.0000"),
                line_amount=Decimal("1010000.0000"),
                purchase_order_line_id=po_line_id,
            )
        ],
    )

    policy = TolerancePolicy(
        tenant_id=tenant_id,
        price_tolerance_pct=Decimal("0.0200"),
        max_amount_delta=Decimal("50000.0000"),
    )

    report = engine.match_3_way(invoice=inv, po=po, policy=policy)
    assert report.is_matched is True
    assert report.status == MatchStatus.MATCHED_WITHIN_TOLERANCE
    assert report.requires_review is False


def test_multi_signal_verifier_keeps_vision_values_model_proposed_despite_arithmetic():
    """Arithmetic consistency cannot verify numbers that a Vision model produced itself."""
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="0001235",
        subtotal=Decimal("2000000.0000"),
        tax_total=Decimal("200000.0000"),
        amount_payable=Decimal("2200000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Thiết bị",
                qty=Decimal("2.0000"),
                unit_price=Decimal("1000000.0000"),
                line_amount=Decimal("2000000.0000"),
            )
        ],
        evidence=[
            FieldEvidence(field_path=path, source_kind="vision_llm", extractor="openai_vision")
            for path in (
                "subtotal",
                "tax_total",
                "amount_payable",
                "lines[0].unit_price",
                "lines[0].line_amount",
            )
        ],
    )

    verified = MultiSignalVerifier().verify_invoice(inv)
    states = {ev.field_path: ev.verification_state for ev in verified.evidence}

    for path in (
        "subtotal",
        "tax_total",
        "amount_payable",
        "lines[0].unit_price",
        "lines[0].line_amount",
    ):
        assert states[path] == FieldVerificationState.MODEL_PROPOSED, path


def test_multi_signal_verifier_marks_unextracted_and_unlocated_fields():
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="0105554321",
        invoice_number="0003412",
        subtotal=Decimal("1000000.0000"),
        tax_total=Decimal("0.0000"),
        amount_payable=Decimal("1100000.0000"),
        evidence=[
            FieldEvidence(
                field_path="subtotal",
                source_kind="pdf",
                normalized_value="1000000.0000",
                review_reason="no_direct_text_match",
            )
        ],
        parser_issues=["TAX_TOTAL_NOT_FOUND"],
    )

    states = {
        ev.field_path: ev.verification_state
        for ev in MultiSignalVerifier().verify_invoice(inv).evidence
    }

    assert states["tax_total"] == FieldVerificationState.MISSING
    assert states["subtotal"] == FieldVerificationState.UNCERTAIN


def test_multi_signal_verifier_uses_the_configured_confidence_threshold():
    inv = InvoiceAggregate(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        supplier_tax_id="0100109106",
        supplier_name="Cong ty A",
        evidence=[
            FieldEvidence(field_path="supplier_name", source_kind="pdf", confidence=0.8),
        ],
    )

    strict = {
        ev.field_path: ev.verification_state
        for ev in MultiSignalVerifier(min_field_confidence=0.9).verify_invoice(inv).evidence
    }
    lenient = {
        ev.field_path: ev.verification_state
        for ev in MultiSignalVerifier(min_field_confidence=0.5).verify_invoice(inv).evidence
    }

    assert strict["supplier_name"] == FieldVerificationState.UNCERTAIN
    assert lenient["supplier_name"] == FieldVerificationState.VALID
