import uuid
from pathlib import Path
import pytest
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter
from invoiceflow.domain.documents.models import CanonicalDocument


def test_docling_adapter_extracts_canonical_document():
    fixture_path = Path("benchmarks/fixtures/documents/case_02.pdf")
    if not fixture_path.exists():
        pytest.skip("Fixture case_02.pdf not found")

    pdf_bytes = fixture_path.read_bytes()
    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    adapter = DoclingAdapter()
    canonical = adapter.extract_canonical(
        tenant_id=tenant_id,
        document_id=doc_id,
        pdf_bytes=pdf_bytes,
        do_ocr=False,
    )

    assert isinstance(canonical, CanonicalDocument)
    assert canonical.document_id == doc_id
    assert canonical.tenant_id == tenant_id
    assert canonical.source_format == "pdf"
    assert len(canonical.elements) > 0
    assert len(canonical.tables) > 0

    first_table = canonical.tables[0]
    assert first_table.row_count > 0
    assert first_table.column_count > 0
    assert len(first_table.cells) > 0

    # Ensure elements have valid bounding boxes
    elements_with_bbox = [el for el in canonical.elements if el.bbox is not None]
    assert len(elements_with_bbox) > 0
    first_bbox = elements_with_bbox[0].bbox
    assert first_bbox.x1 >= first_bbox.x0
    assert first_bbox.y1 >= first_bbox.y0


def test_docling_adapter_fallback_on_corrupt_data():
    corrupt_bytes = b"NOT_A_VALID_PDF_STREAM"
    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    adapter = DoclingAdapter()
    canonical = adapter.extract_canonical(
        tenant_id=tenant_id,
        document_id=doc_id,
        pdf_bytes=corrupt_bytes,
    )

    assert isinstance(canonical, CanonicalDocument)
    assert "fallback_from" in canonical.metadata
    assert canonical.metadata["fallback_from"] == "docling"
