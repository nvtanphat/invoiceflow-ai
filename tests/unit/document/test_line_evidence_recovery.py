from decimal import Decimal
import uuid

from invoiceflow.application.processing.line_evidence_recovery import (
    ground_text_lines,
    recover_merged_quantities,
)
from invoiceflow.domain.documents.models import BoundingBox, CanonicalDocument, DocumentElement
from invoiceflow.domain.invoices.models import FieldEvidence, FieldVerificationState, InvoiceLine

_MERGE_ISSUES = [
    "QTY_ZERO_OR_MISSING",
    "QTY_UNRECOVERED",
    "CELL_MERGE_SUSPECTED",
    "ARITHMETIC_MISMATCH",
]


def _merged_line(description: str, price: str, amount: str) -> InvoiceLine:
    return InvoiceLine(
        line_no=1,
        sku_ref="PAPER-A4-70",
        description=description,
        qty=Decimal("0"),
        unit_price=Decimal(price),
        line_amount=Decimal(amount),
        issues=list(_MERGE_ISSUES),
    )


def _description_evidence(cell_text: str) -> FieldEvidence:
    return FieldEvidence(
        field_path="lines[0].description",
        source_kind="pdf_table",
        raw_value=cell_text,
        cell_id="tbl-r1-c1",
        bbox=BoundingBox(page_index=0, x0=40, y0=200, x1=300, y1=215),
    )


def test_quantity_printed_in_merged_description_cell_is_recovered_with_cell_evidence():
    """Regression (case_04/case_06): TableFormer fused the quantity into the description cell."""
    line = _merged_line("Giấy photocopy Double A A4 70gsm 200.000", "63000.0000", "12600000.0000")
    cell_text = "Giấy photocopy Double A A4 70gsm [PAPER-A4-70] 200.000"

    lines, evidence = recover_merged_quantities([line], [_description_evidence(cell_text)])

    assert lines[0].qty == Decimal("200.000")
    assert lines[0].issues == []
    assert lines[0].description == "Giấy photocopy Double A A4 70gsm"
    qty_ev = next(ev for ev in evidence if ev.field_path == "lines[0].qty")
    assert qty_ev.cell_id == "tbl-r1-c1"
    assert qty_ev.raw_value == cell_text
    assert qty_ev.verification_state == FieldVerificationState.ARITHMETICALLY_CONSISTENT


def test_trailing_number_that_does_not_reconcile_is_not_taken_as_quantity():
    line = _merged_line("Laptop Dell XPS 13", "25000000.0000", "50000000.0000")

    lines, evidence = recover_merged_quantities(
        [line], [_description_evidence("Laptop Dell XPS 13")]
    )

    assert lines[0].qty == Decimal("0")
    assert "QTY_UNRECOVERED" in lines[0].issues
    assert not any(ev.field_path == "lines[0].qty" for ev in evidence)


def test_merged_cell_without_trailing_number_is_left_for_other_recovery():
    line = _merged_line("Chuột dây Logitech không", "2000000.0000", "10000000.0000")

    lines, _ = recover_merged_quantities(
        [line], [_description_evidence("Chuột dây Logitech [MOUSE-LOGI.0000 không")]
    )

    assert lines[0].qty == Decimal("0")


def _doc(*texts: str) -> CanonicalDocument:
    return CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2",
        config_hash="h",
        page_count=1,
        elements=[
            DocumentElement(
                id=f"el-{i}",
                page_index=0,
                text=text,
                bbox=BoundingBox(page_index=0, x0=10, y0=10 + 20 * i, x1=400, y1=25 + 20 * i),
            )
            for i, text in enumerate(texts)
        ],
    )


_CASE_03_TEXT = (
    "Hang hoa: Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng [CLEAN-SET-01]",
    "So luong: 10.0000 Don gia: 850000.0000 Thue: 8.00%",
    "Tien hang: 8500000.0000 Thue GTGT: 680000.0000 Tong cong: 9180000.0000",
)


def _case_03_line() -> InvoiceLine:
    return InvoiceLine(
        line_no=1,
        sku_ref="CLEAN-SET-01",
        description="Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng",
        qty=Decimal("10.0000"),
        unit_price=Decimal("850000.0000"),
        line_amount=Decimal("8500000.0000"),
    )


def test_text_layout_line_values_are_grounded_in_the_line_block():
    evidence = {
        ev.field_path: ev
        for ev in ground_text_lines(
            [_case_03_line()], _doc(*_CASE_03_TEXT), subtotal_confirmed=True
        )
    }

    assert evidence["lines[0].qty"].raw_value == _CASE_03_TEXT[1]
    assert evidence["lines[0].qty"].bbox.y0 == 30
    assert evidence["lines[0].unit_price"].raw_value == _CASE_03_TEXT[1]
    amount = evidence["lines[0].line_amount"]
    # Not printed per line: derived from grounded qty x price, never borrowed from the summary.
    assert amount.source_kind == "arithmetic_derivation"
    assert amount.bbox is None
    assert amount.verification_state == FieldVerificationState.ARITHMETICALLY_CONSISTENT


def test_unprinted_line_amount_is_not_derived_unless_printed_subtotal_confirms_it():
    paths = {
        ev.field_path
        for ev in ground_text_lines(
            [_case_03_line()], _doc(*_CASE_03_TEXT), subtotal_confirmed=False
        )
    }

    assert paths == {"lines[0].qty", "lines[0].unit_price"}


def test_values_outside_the_line_block_are_not_grounded():
    doc = _doc(
        "Hang hoa: Bộ dụng cụ [CLEAN-SET-01]",
        "Tong cong: 9180000.0000",
        "So luong: 10.0000 Don gia: 850000.0000",
    )

    assert ground_text_lines([_case_03_line()], doc, subtotal_confirmed=True) == []
