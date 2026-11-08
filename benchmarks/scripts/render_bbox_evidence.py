"""Renders a fixture PDF page with the extracted line-item field bounding
boxes drawn on top, as visual proof that evidence grounding (table_id,
cell_id, page_index, bbox) resolves to the correct location on the source
document rather than just existing as unverified metadata.
"""

import sys
from pathlib import Path

import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter  # noqa: E402
from invoiceflow.infrastructure.document.table_extractor import (  # noqa: E402
    StructureAwareTableExtractor,
)

FIXTURES_DIR = ROOT_DIR / "benchmarks" / "fixtures" / "documents"
OUTPUT_DIR = ROOT_DIR / "benchmarks" / "results" / "evidence"


def render(case_filename: str, do_ocr: bool = False) -> Path:
    pdf_path = FIXTURES_DIR / case_filename
    pdf_bytes = pdf_path.read_bytes()

    canonical_doc = DoclingAdapter().extract_canonical(
        tenant_id="evidence-proof",
        document_id="evidence-proof",
        pdf_bytes=pdf_bytes,
        do_ocr=do_ocr,
    )
    lines, evidence = StructureAwareTableExtractor().extract_lines_with_evidence(
        canonical_doc.tables
    )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        page_evidence = [ev for ev in evidence if ev.bbox and ev.bbox.page_index == page.number]
        for ev in page_evidence:
            rect = fitz.Rect(ev.bbox.x0, ev.bbox.y0, ev.bbox.x1, ev.bbox.y1)
            page.draw_rect(rect, color=(0.85, 0.1, 0.1), width=1.2)
            page.insert_text(
                (rect.x0, max(rect.y0 - 3, 8)),
                f"{ev.field_path} [{ev.table_id}/{ev.cell_id}]",
                fontsize=6,
                color=(0.85, 0.1, 0.1),
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{pdf_path.stem}_bbox_evidence.png"
    pix = doc[0].get_pixmap(dpi=150)
    pix.save(str(out_path))
    doc.close()

    print(f"Lines extracted: {len(lines)}")
    print(f"Evidence entries: {len(evidence)}")
    for ev in evidence:
        print(
            f"  {ev.field_path}: table_id={ev.table_id} cell_id={ev.cell_id} page={ev.page_index}"
        )
    print(f"Rendered: {out_path}")
    return out_path


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "case_06.pdf"
    render(case)
