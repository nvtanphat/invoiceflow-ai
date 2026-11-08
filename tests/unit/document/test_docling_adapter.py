from pathlib import Path
import uuid
import pytest
from invoiceflow.domain.documents.models import CanonicalDocument
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter


def test_docling_adapter_extracts_canonical_document_without_fallback():
    pytest.importorskip(
        "docling",
        reason="Docling is an optional dependency (install with pip install '.[documents]')",
    )
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
    # Verify real Docling ran without fallback
    assert canonical.parser_name == "docling"
    assert "fallback_from" not in canonical.metadata
    assert canonical.metadata["engine"] == "docling"

    # Verify structural table extraction
    assert len(canonical.tables) > 0
    first_table = canonical.tables[0]
    assert first_table.row_count > 0
    assert first_table.column_count > 0
    assert len(first_table.cells) > 0

    # Verify elements, reading order and bounding boxes
    assert len(canonical.elements) > 0
    for idx, el in enumerate(canonical.elements, start=1):
        assert el.reading_order == idx
        assert el.text is not None

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


def test_docling_adapter_converter_cache_separation():
    pytest.importorskip("docling")
    adapter = DoclingAdapter()
    c_no_ocr = adapter._get_converter(do_ocr=False)
    c_ocr = adapter._get_converter(do_ocr=True)
    assert c_no_ocr is not c_ocr
    assert False in adapter._converters
    assert True in adapter._converters


def test_docling_adapter_defaults_ocr_engine_from_settings():
    from invoiceflow.config import get_settings

    settings = get_settings()
    adapter = DoclingAdapter()
    assert adapter._ocr_engine == settings.OCR_ENGINE
    assert adapter._ocr_languages == list(settings.OCR_LANGUAGES)


def test_docling_adapter_explicit_ocr_engine_overrides_settings():
    adapter = DoclingAdapter(ocr_engine="rapidocr", ocr_languages=["en"])
    assert adapter._ocr_engine == "rapidocr"
    assert adapter._ocr_languages == ["en"]


def test_docling_adapter_builds_easyocr_pipeline_options():
    pytest.importorskip("docling")
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import EasyOcrOptions

    adapter = DoclingAdapter(ocr_engine="easyocr", ocr_languages=["vi", "en"])
    converter = adapter._get_converter(do_ocr=True)
    pdf_opts = converter.format_to_options[InputFormat.PDF].pipeline_options

    assert isinstance(pdf_opts.ocr_options, EasyOcrOptions)
    assert pdf_opts.ocr_options.lang == ["vi", "en"]


def test_docling_adapter_empty_document_fallback():
    import fitz

    # Create empty 1-page PDF
    doc = fitz.open()
    doc.new_page()
    blank_bytes = doc.write()
    doc.close()

    adapter = DoclingAdapter()
    canonical = adapter.extract_canonical(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        pdf_bytes=blank_bytes,
        do_ocr=False,
    )
    assert isinstance(canonical, CanonicalDocument)
    assert "fallback_from" in canonical.metadata
