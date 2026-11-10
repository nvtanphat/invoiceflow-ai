import uuid
from invoiceflow.domain.documents.models import (
    BoundingBox,
    CanonicalDocument,
    DocumentElement,
)


def test_evidence_mapper_maps_fields_to_elements():
    from invoiceflow.application.processing.evidence_mapper import EvidenceMapper

    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    canonical_doc = CanonicalDocument(
        document_id=doc_id,
        tenant_id=tenant_id,
        source_format="pdf",
        parser_name="pymupdf",
        parser_version="1.25.0",
        config_hash="abc",
        page_count=1,
        elements=[
            DocumentElement(
                id="el-1",
                page_index=0,
                text="Công ty TNHH Mẫu",
                bbox=BoundingBox(page_index=0, x0=50, y0=50, x1=200, y1=70),
            ),
            DocumentElement(
                id="el-2",
                page_index=0,
                text="Số hóa đơn: INV-9999",
                bbox=BoundingBox(page_index=0, x0=50, y0=80, x1=200, y1=100),
            ),
            DocumentElement(
                id="el-3",
                page_index=0,
                text="Tổng cộng: 2.500.000 VND",
                bbox=BoundingBox(page_index=0, x0=50, y0=250, x1=250, y1=270),
            ),
        ],
    )

    mapper = EvidenceMapper()
    extracted_fields = {
        "supplier_name": "Công ty TNHH Mẫu",
        "invoice_number": "INV-9999",
        "amount_payable": "2500000.00",
        "unmatched_field": "Non existent text",
    }

    evidence_list = mapper.map_evidence(extracted_fields, canonical_doc)
    ev_map = {ev.field_path: ev for ev in evidence_list}

    assert "supplier_name" in ev_map
    assert ev_map["supplier_name"].page_index == 0
    assert ev_map["supplier_name"].bbox is not None
    assert ev_map["supplier_name"].bbox.x0 == 50

    assert "invoice_number" in ev_map
    assert ev_map["invoice_number"].raw_value == "Số hóa đơn: INV-9999"

    # Unmatched field is recorded with null bbox and unverified reason
    assert "unmatched_field" in ev_map
    assert ev_map["unmatched_field"].bbox is None
    assert ev_map["unmatched_field"].review_reason == "no_direct_text_match"


def _doc(*texts: str):
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
                bbox=BoundingBox(page_index=0, x0=10, y0=10 + 20 * i, x1=300, y1=25 + 20 * i),
            )
            for i, text in enumerate(texts)
        ],
    )


def test_evidence_mapper_matches_money_by_value_and_prefers_labelled_element():
    from invoiceflow.application.processing.evidence_mapper import EvidenceMapper

    doc = _doc(
        "Bộ dụng cụ vệ sinh 10 850.000 8.500.000",
        "Cộng tiền hàng: 8.500.000 đ",
        "Tiền thuế GTGT (8%): 680.000",
    )

    evidence = {
        ev.field_path: ev
        for ev in EvidenceMapper().map_evidence(
            {"subtotal": "8500000.0000", "tax_total": "680000.0000"}, doc
        )
    }

    assert evidence["subtotal"].raw_value == "Cộng tiền hàng: 8.500.000 đ"
    assert evidence["subtotal"].bbox.y0 == 30
    assert evidence["tax_total"].raw_value == "Tiền thuế GTGT (8%): 680.000"


def test_evidence_mapper_matches_dates_across_formats():
    from invoiceflow.application.processing.evidence_mapper import EvidenceMapper

    doc = _doc("Ngày 08 tháng 03 năm 2026", "Ngày lập: 12/03/2026")

    evidence = {
        ev.field_path: ev for ev in EvidenceMapper().map_evidence({"issue_date": "2026-03-12"}, doc)
    }

    assert evidence["issue_date"].raw_value == "Ngày lập: 12/03/2026"


def test_evidence_mapper_does_not_claim_source_for_unlocated_values():
    from invoiceflow.application.processing.evidence_mapper import EvidenceMapper
    from invoiceflow.domain.invoices.models import FieldVerificationState

    doc = _doc("Tổng cộng: 9.180.000")

    evidence = EvidenceMapper().map_evidence({"subtotal": "8500000.0000"}, doc)[0]

    assert evidence.bbox is None
    assert evidence.raw_value is None
    assert evidence.verification_state == FieldVerificationState.UNCERTAIN
