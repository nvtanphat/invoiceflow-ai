from invoiceflow.domain.documents.models import (
    BoundingBox,
    CanonicalDocument,
    DocumentCell,
    DocumentElement,
    DocumentTable,
)


def test_canonical_document_provenance_and_roundtrip():
    doc_id = "doc-test-provenance-001"
    tenant_id = "tenant-test-001"

    bbox = BoundingBox(
        page_index=0,
        x0=50.0,
        y0=100.0,
        x1=250.0,
        y1=120.0,
        page_width=595.0,
        page_height=842.0,
        rotation=0,
    )

    cell = DocumentCell(
        id="cell-0-1",
        table_id="table-1",
        row_index=0,
        col_index=1,
        text="Máy tính Dell",
        raw_text="Máy tính Dell\n",
        normalized_text="Máy tính Dell",
        bbox=bbox,
        confidence=0.98,
    )

    table = DocumentTable(
        id="table-1",
        page_index=0,
        row_count=1,
        column_count=2,
        cells=[cell],
        bbox=bbox,
        confidence=0.95,
    )

    element = DocumentElement(
        id="elem-1",
        page_index=0,
        kind="title",
        text="HÓA ĐƠN GIÁ TRỊ GIA TĂNG",
        raw_text="HÓA ĐƠN GIÁ TRỊ GIA TĂNG  ",
        normalized_text="HÓA ĐƠN GIÁ TRỊ GIA TĂNG",
        bbox=bbox,
        reading_order=1,
        parent_id=None,
        confidence=0.99,
    )

    canonical = CanonicalDocument(
        document_id=doc_id,
        tenant_id=tenant_id,
        source_format="pdf",
        parser_name="docling_enhanced",
        parser_version="2.87.0",
        config_hash="abc123hash",
        source_checksum="sha256:fedcba9876543210",
        page_count=1,
        page_rotations={0: 0},
        elements=[element],
        tables=[table],
        metadata={"ocr_engine": "rapidocr", "dpi": 150},
    )

    # 1. Verification of enhanced fields
    assert canonical.source_checksum == "sha256:fedcba9876543210"
    assert canonical.document_id == "doc-test-provenance-001"
    assert canonical.elements[0].raw_text == "HÓA ĐƠN GIÁ TRỊ GIA TĂNG  "
    assert canonical.tables[0].cells[0].table_id == "table-1"
    assert canonical.tables[0].cells[0].confidence == 0.98
    assert canonical.elements[0].bbox.page_width == 595.0

    # 2. Serialization & Deserialization roundtrip
    data = canonical.model_dump()
    reconstituted = CanonicalDocument.model_validate(data)
    assert reconstituted.document_id == canonical.document_id
    assert reconstituted.tables[0].cells[0].normalized_text == "Máy tính Dell"
    assert reconstituted.metadata["ocr_engine"] == "rapidocr"
