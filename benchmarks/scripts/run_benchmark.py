import asyncio
import csv
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional
import uuid
import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from benchmarks.scripts.evaluator import (  # noqa: E402
    average_arithmetic_validity,
    evaluate_prediction,
)
from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute  # noqa: E402
from invoiceflow.application.reconciliation.matching_engine import MatchingEngine  # noqa: E402
from invoiceflow.config import get_settings  # noqa: E402
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceLine  # noqa: E402
from invoiceflow.domain.policies.models import TolerancePolicy  # noqa: E402
from invoiceflow.domain.purchasing.models import (  # noqa: E402
    GoodsReceipt,
    GRNLine,
    POLine,
    PurchaseOrder,
)
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser  # noqa: E402
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter  # noqa: E402
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector  # noqa: E402
from invoiceflow.infrastructure.document.table_extractor import StructureAwareTableExtractor  # noqa: E402
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser, XMLParsingError  # noqa: E402
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter  # noqa: E402

FIXTURES_DIR = ROOT_DIR / "benchmarks" / "fixtures"
DOCS_DIR = FIXTURES_DIR / "documents"


def load_manifest() -> List[Dict[str, Any]]:
    manifest_path = FIXTURES_DIR / "casebook_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_fixture_file(case_id: str) -> Path:
    mapping = {
        "CASE-01-XML-STANDARD": DOCS_DIR / "case_01.xml",
        "CASE-02-PDF-DIGITAL": DOCS_DIR / "case_02.pdf",
        "CASE-03-PDF-SCAN": DOCS_DIR / "case_03.pdf",
        "CASE-04-DISCREPANCY-PRICE": DOCS_DIR / "case_04.pdf",
        "CASE-05-DISCREPANCY-QTY": DOCS_DIR / "case_05.xml",
        "CASE-06-PDF-MULTI-LINE": DOCS_DIR / "case_06.pdf",
        "CASE-07-PDF-ROTATED-SCAN": DOCS_DIR / "case_07.pdf",
        "CASE-08-PDF-COMPLEX-AMOUNTS": DOCS_DIR / "case_08.pdf",
        "CASE-09-PDF-MIXED": DOCS_DIR / "case_09.pdf",
        "CASE-10-PDF-SCAN-TABLE": DOCS_DIR / "case_10.pdf",
    }
    return mapping[case_id]


def get_demo_po_and_grn(supplier_tax_id: Optional[str], case_id: Optional[str] = None):
    tenant_id = uuid.uuid4()
    if case_id == "CASE-06-PDF-MULTI-LINE":
        po_id = uuid.uuid4()
        lines = [
            POLine(
                id=uuid.uuid4(),
                po_id=po_id,
                line_no=1,
                sku="DELL-XPS-13",
                description="Máy tính xách tay Dell XPS 13",
                ordered_qty=Decimal("2.0000"),
                unit_price=Decimal("25000000.0000"),
                line_total=Decimal("50000000.0000"),
            ),
            POLine(
                id=uuid.uuid4(),
                po_id=po_id,
                line_no=2,
                sku="MOUSE-LOGI",
                description="Chuột không dây Logitech MX Master 3S",
                ordered_qty=Decimal("5.0000"),
                unit_price=Decimal("2000000.0000"),
                line_total=Decimal("10000000.0000"),
            ),
            POLine(
                id=uuid.uuid4(),
                po_id=po_id,
                line_no=3,
                sku="KEY-MECH-01",
                description="Bàn phím cơ Keychron K2 Pro",
                ordered_qty=Decimal("5.0000"),
                unit_price=Decimal("2000000.0000"),
                line_total=Decimal("10000000.0000"),
            ),
        ]
        po = PurchaseOrder(
            id=po_id,
            tenant_id=tenant_id,
            po_number="PO-2026-006",
            vendor_tax_id="0101234567",
            vendor_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
            order_date=date(2026, 3, 9),
            currency="VND",
            subtotal=Decimal("70000000.0000"),
            lines=lines,
        )
        grn_id = uuid.uuid4()
        grn_lines = [
            GRNLine(
                id=uuid.uuid4(),
                grn_id=grn_id,
                po_line_id=line.id,
                line_no=idx,
                received_qty=line.ordered_qty,
            )
            for idx, line in enumerate(lines, start=1)
        ]
        grn = GoodsReceipt(
            id=grn_id,
            tenant_id=tenant_id,
            po_id=po_id,
            grn_number="GRN-2026-006",
            receipt_date=date(2026, 3, 10),
            lines=grn_lines,
        )
        return po, [grn]

    if case_id == "CASE-10-PDF-SCAN-TABLE":
        po_id = uuid.uuid4()
        lines = [
            POLine(
                id=uuid.uuid4(),
                po_id=po_id,
                line_no=1,
                sku="DELL-XPS-13",
                description="Máy tính xách tay Dell XPS 13",
                ordered_qty=Decimal("2.0000"),
                unit_price=Decimal("25000000.0000"),
                line_total=Decimal("50000000.0000"),
            ),
            POLine(
                id=uuid.uuid4(),
                po_id=po_id,
                line_no=2,
                sku="MOUSE-LOGI",
                description="Chuột không dây Logitech MX Master 3S",
                ordered_qty=Decimal("5.0000"),
                unit_price=Decimal("2000000.0000"),
                line_total=Decimal("10000000.0000"),
            ),
        ]
        po = PurchaseOrder(
            id=po_id,
            tenant_id=tenant_id,
            po_number="PO-2026-010",
            vendor_tax_id="0101234567",
            vendor_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
            order_date=date(2026, 3, 19),
            currency="VND",
            subtotal=Decimal("60000000.0000"),
            lines=lines,
        )
        grn_id = uuid.uuid4()
        grn_lines = [
            GRNLine(
                id=uuid.uuid4(),
                grn_id=grn_id,
                po_line_id=line.id,
                line_no=idx,
                received_qty=line.ordered_qty,
            )
            for idx, line in enumerate(lines, start=1)
        ]
        grn = GoodsReceipt(
            id=grn_id,
            tenant_id=tenant_id,
            po_id=po_id,
            grn_number="GRN-2026-010",
            receipt_date=date(2026, 3, 20),
            lines=grn_lines,
        )
        return po, [grn]

    if supplier_tax_id == "0101234567":
        po_id = uuid.uuid4()
        po_line_id = uuid.uuid4()
        po = PurchaseOrder(
            id=po_id,
            tenant_id=tenant_id,
            po_number="PO-2026-001",
            vendor_tax_id="0101234567",
            vendor_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
            order_date=date(2026, 3, 1),
            currency="VND",
            subtotal=Decimal("50000000.0000"),
            lines=[
                POLine(
                    id=po_line_id,
                    po_id=po_id,
                    line_no=1,
                    sku="DELL-XPS-13",
                    description="Máy tính xách tay Dell XPS 13 i7/16GB/512GB",
                    ordered_qty=Decimal("5.0000"),
                    unit_price=Decimal("10000000.0000"),
                    line_total=Decimal("50000000.0000"),
                )
            ],
        )
        grn_id = uuid.uuid4()
        grn = GoodsReceipt(
            id=grn_id,
            tenant_id=tenant_id,
            po_id=po_id,
            grn_number="GRN-2026-001",
            receipt_date=date(2026, 3, 2),
            lines=[
                GRNLine(
                    id=uuid.uuid4(),
                    grn_id=grn_id,
                    po_line_id=po_line_id,
                    line_no=1,
                    received_qty=Decimal("5.0000"),
                )
            ],
        )
        return po, [grn]

    if supplier_tax_id == "0105554321":
        po_id = uuid.uuid4()
        po_line_id = uuid.uuid4()
        po = PurchaseOrder(
            id=po_id,
            tenant_id=tenant_id,
            po_number="PO-2026-003",
            vendor_tax_id="0105554321",
            vendor_name="Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội",
            order_date=date(2026, 3, 7),
            currency="VND",
            subtotal=Decimal("8500000.0000"),
            lines=[
                POLine(
                    id=po_line_id,
                    po_id=po_id,
                    line_no=1,
                    sku="CLEAN-SET-01",
                    description="Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng",
                    ordered_qty=Decimal("10.0000"),
                    unit_price=Decimal("850000.0000"),
                    line_total=Decimal("8500000.0000"),
                )
            ],
        )
        grn_id = uuid.uuid4()
        grn = GoodsReceipt(
            id=grn_id,
            tenant_id=tenant_id,
            po_id=po_id,
            grn_number="GRN-2026-003",
            receipt_date=date(2026, 3, 8),
            lines=[
                GRNLine(
                    id=uuid.uuid4(),
                    grn_id=grn_id,
                    po_line_id=po_line_id,
                    line_no=1,
                    received_qty=Decimal("10.0000"),
                )
            ],
        )
        return po, [grn]

    # Default: Vendor 0309876543 (Giấy Miền Nam)
    po_id = uuid.uuid4()
    po_line_id = uuid.uuid4()
    po = PurchaseOrder(
        id=po_id,
        tenant_id=tenant_id,
        po_number="PO-2026-002",
        vendor_tax_id="0309876543",
        vendor_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
        order_date=date(2026, 3, 5),
        currency="VND",
        subtotal=Decimal("12000000.0000"),
        lines=[
            POLine(
                id=po_line_id,
                po_id=po_id,
                line_no=1,
                sku="PAPER-A4-70",
                description="Giấy photocopy Double A A4 70gsm",
                ordered_qty=Decimal("200.0000"),
                unit_price=Decimal("60000.0000"),
                line_total=Decimal("12000000.0000"),
            )
        ],
    )

    grn_id = uuid.uuid4()
    grn = GoodsReceipt(
        id=grn_id,
        tenant_id=tenant_id,
        po_id=po_id,
        grn_number="GRN-2026-002",
        receipt_date=date(2026, 3, 5),
        lines=[
            GRNLine(
                id=uuid.uuid4(),
                grn_id=grn_id,
                po_line_id=po_line_id,
                line_no=1,
                received_qty=Decimal("200.0000"),
            )
        ],
    )
    return po, [grn]


def run_b0_xml_direct(case: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []

    if file_path.suffix == ".xml":
        with open(file_path, "rb") as f:
            content = f.read()
        parser = SecureXMLParser()
        try:
            inv = parser.parse_invoice_xml(uuid.uuid4(), uuid.uuid4(), content)
            header = {
                "supplier_tax_id": inv.supplier_tax_id,
                "supplier_name": inv.supplier_name,
                "buyer_tax_id": inv.buyer_tax_id,
                "buyer_name": inv.buyer_name,
                "invoice_number": inv.invoice_number,
                "invoice_series": inv.invoice_series,
                "issue_date": str(inv.issue_date) if inv.issue_date else None,
                "currency": inv.currency,
                "subtotal": str(inv.subtotal),
                "tax_total": str(inv.tax_total),
                "amount_payable": str(inv.amount_payable),
            }
            for line in inv.lines:
                m_sku = re.search(r"\[([A-Z0-9_-]+)\]", line.description)
                sku_val = line.sku_ref or (m_sku.group(1) if m_sku else "")
                lines.append(
                    {
                        "sku": sku_val,
                        "description": line.description,
                        "qty": str(line.qty),
                        "unit_price": str(line.unit_price),
                        "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                        "line_amount": str(line.line_amount),
                    }
                )
        except XMLParsingError:
            pass

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "baseline_id": "B0_XML_DIRECT",
        "header": header,
        "lines": lines,
        "detected_discrepancies": [],
        "latency_ms": round(duration_ms, 2),
        "cost_usd": 0.0000,
    }


def run_b1_pymupdf_rules(case: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []

    if file_path.suffix == ".xml":
        res = run_b0_xml_direct(case, file_path)
        header = res["header"]
        lines = res["lines"]
    else:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join([page.get_text() for page in doc])
        doc.close()
        parser = DigitalPDFParser()
        ext = parser.parse(text)
        header = {
            "supplier_tax_id": ext.supplier_tax_id or "",
            "supplier_name": ext.supplier_name or "",
            "buyer_tax_id": ext.buyer_tax_id or "",
            "buyer_name": ext.buyer_name or "",
            "invoice_number": ext.invoice_number or "",
            "invoice_series": ext.invoice_series or "",
            "issue_date": ext.issue_date or "",
            "currency": ext.currency,
            "subtotal": str(ext.subtotal),
            "tax_total": str(ext.tax_total),
            "amount_payable": str(ext.amount_payable),
        }
        lines = [
            {
                "sku": line.sku or "",
                "description": line.description,
                "qty": str(line.qty),
                "unit_price": str(line.unit_price),
                "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                "line_amount": str(line.line_amount),
            }
            for line in ext.lines
        ]

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "baseline_id": "B1_PYMUPDF_RULES",
        "header": header,
        "lines": lines,
        "detected_discrepancies": [],
        "latency_ms": round(duration_ms, 2),
        "cost_usd": 0.0000,
    }


def run_b2_docling_text_rules(case: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []

    if file_path.suffix == ".xml":
        res = run_b0_xml_direct(case, file_path)
        header = res["header"]
        lines = res["lines"]
    else:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        docling_adapter = DoclingAdapter()
        canonical_doc = docling_adapter.extract_canonical(
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            pdf_bytes=pdf_bytes,
            do_ocr=False,
        )
        full_text = "\n".join([el.text for el in canonical_doc.elements])
        parser = DigitalPDFParser()
        ext = parser.parse(full_text)
        header = {
            "supplier_tax_id": ext.supplier_tax_id or "",
            "supplier_name": ext.supplier_name or "",
            "buyer_tax_id": ext.buyer_tax_id or "",
            "buyer_name": ext.buyer_name or "",
            "invoice_number": ext.invoice_number or "",
            "invoice_series": ext.invoice_series or "",
            "issue_date": ext.issue_date or "",
            "currency": ext.currency,
            "subtotal": str(ext.subtotal),
            "tax_total": str(ext.tax_total),
            "amount_payable": str(ext.amount_payable),
        }
        lines = [
            {
                "sku": line.sku or "",
                "description": line.description,
                "qty": str(line.qty),
                "unit_price": str(line.unit_price),
                "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                "line_amount": str(line.line_amount),
            }
            for line in ext.lines
        ]

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "baseline_id": "B2_DOCLING_TEXT_RULES",
        "header": header,
        "lines": lines,
        "detected_discrepancies": [],
        "latency_ms": round(duration_ms, 2),
        "cost_usd": 0.0000,
    }


def run_b3_docling_ocr_structured(case: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []

    if file_path.suffix == ".xml":
        res = run_b0_xml_direct(case, file_path)
        header = res["header"]
        lines = res["lines"]
    else:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        docling_adapter = DoclingAdapter()
        canonical_doc = docling_adapter.extract_canonical(
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            pdf_bytes=pdf_bytes,
            do_ocr=True,
        )

        table_extractor = StructureAwareTableExtractor()
        extracted_lines = table_extractor.extract_lines(canonical_doc.tables)
        if extracted_lines:
            lines = [
                {
                    "sku": line_item.sku_ref or "",
                    "description": line_item.description,
                    "qty": str(line_item.qty),
                    "unit_price": str(line_item.unit_price),
                    "tax_rate": str(line_item.tax_rate) if line_item.tax_rate else None,
                    "line_amount": str(line_item.line_amount),
                }
                for line_item in extracted_lines
            ]

        full_text = "\n".join([el.text for el in canonical_doc.elements])
        parser = DigitalPDFParser()
        ext = parser.parse(full_text)
        header = {
            "supplier_tax_id": ext.supplier_tax_id or "",
            "supplier_name": ext.supplier_name or "",
            "buyer_tax_id": ext.buyer_tax_id or "",
            "buyer_name": ext.buyer_name or "",
            "invoice_number": ext.invoice_number or "",
            "invoice_series": ext.invoice_series or "",
            "issue_date": ext.issue_date or "",
            "currency": ext.currency,
            "subtotal": str(ext.subtotal),
            "tax_total": str(ext.tax_total),
            "amount_payable": str(ext.amount_payable),
        }
        if not lines:
            lines = [
                {
                    "sku": line.sku or "",
                    "description": line.description,
                    "qty": str(line.qty),
                    "unit_price": str(line.unit_price),
                    "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                    "line_amount": str(line.line_amount),
                }
                for line in ext.lines
            ]

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "baseline_id": "B3_DOCLING_OCR_STRUCTURED",
        "header": header,
        "lines": lines,
        "detected_discrepancies": [],
        "latency_ms": round(duration_ms, 2),
        "cost_usd": 0.0000,
    }


async def run_b4_pure_vision_llm(
    case: Dict[str, Any], file_path: Path, adapter: OpenAIAdapter
) -> Dict[str, Any]:
    start = time.perf_counter()
    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []
    cost = 0.0000

    with open(file_path, "rb") as f:
        content = f.read()

    doc_text = ""
    img_bytes = None
    if file_path.suffix == ".xml":
        doc_text = content.decode("utf-8", errors="ignore")
    else:
        doc = fitz.open(stream=content, filetype="pdf")
        doc_text = doc[0].get_text()
        pix = doc[0].get_pixmap(dpi=96)
        img_bytes = pix.tobytes("png")
        doc.close()

    try:
        ext_res = await adapter.extract_invoice_data(
            document_text=doc_text,
            image_bytes=img_bytes,
        )
        cost = ext_res.cost_usd
        header = {
            "supplier_tax_id": ext_res.supplier_tax_id,
            "supplier_name": ext_res.supplier_name,
            "buyer_tax_id": ext_res.buyer_tax_id,
            "buyer_name": ext_res.buyer_name,
            "invoice_number": ext_res.invoice_number,
            "invoice_series": ext_res.invoice_series,
            "issue_date": ext_res.issue_date,
            "currency": ext_res.currency,
            "subtotal": str(ext_res.subtotal),
            "tax_total": str(ext_res.tax_total),
            "amount_payable": str(ext_res.amount_payable),
        }
        for item in ext_res.line_items:
            m_sku = re.search(r"\[([A-Z0-9_-]+)\]", item.description)
            sku_val = item.sku or (m_sku.group(1) if m_sku else "")
            lines.append(
                {
                    "sku": sku_val,
                    "description": item.description,
                    "qty": str(item.qty),
                    "unit_price": str(item.unit_price),
                    "tax_rate": str(item.tax_rate) if item.tax_rate else None,
                    "line_amount": str(item.line_amount),
                }
            )
    except Exception:
        pass

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "baseline_id": "B4_PURE_VISION_LLM",
        "header": header,
        "lines": lines,
        "detected_discrepancies": [],
        "latency_ms": round(duration_ms, 2),
        "cost_usd": cost,
    }


async def run_b5_invoiceflow_hybrid(
    case: Dict[str, Any], file_path: Path, adapter: OpenAIAdapter
) -> Dict[str, Any]:
    start = time.perf_counter()
    with open(file_path, "rb") as f:
        content = f.read()

    router = DocumentRouter()
    if file_path.suffix == ".xml":
        route = router.decide_route("xml", len(content))
    else:
        inspector = PDFInspector()
        profile = inspector.inspect(content)
        route = router.decide_route(
            detected_kind="pdf",
            file_size_bytes=len(content),
            pdf_classification=profile.classification,
            table_count=profile.table_count,
            has_rotated_pages=profile.has_rotated_pages,
        )

    header: Dict[str, Any] = {}
    lines: List[Dict[str, Any]] = []
    cost = 0.0000

    if route == ProcessingRoute.XML_DETERMINISTIC:
        res = run_b0_xml_direct(case, file_path)
        header = res["header"]
        lines = res["lines"]
        cost = 0.0000
    elif route == ProcessingRoute.VISION_FALLBACK:
        res = await run_b4_pure_vision_llm(case, file_path, adapter)
        header = res["header"]
        lines = res["lines"]
        cost = res.get("cost_usd", 0.0)
    else:
        # Digital or OCR Structured Path
        do_ocr = route == ProcessingRoute.DOCLING_OCR_STRUCTURED
        docling_adapter = DoclingAdapter()
        canonical_doc = docling_adapter.extract_canonical(
            tenant_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            pdf_bytes=content,
            do_ocr=do_ocr,
        )

        table_extractor = StructureAwareTableExtractor()
        extracted_lines = table_extractor.extract_lines(canonical_doc.tables)
        if extracted_lines:
            lines = [
                {
                    "sku": line_item.sku_ref or "",
                    "description": line_item.description,
                    "qty": str(line_item.qty),
                    "unit_price": str(line_item.unit_price),
                    "tax_rate": str(line_item.tax_rate) if line_item.tax_rate else None,
                    "line_amount": str(line_item.line_amount),
                }
                for line_item in extracted_lines
            ]

        full_text = "\n".join([el.text for el in canonical_doc.elements])
        parser = DigitalPDFParser()
        ext = parser.parse(full_text)
        header = {
            "supplier_tax_id": ext.supplier_tax_id or "",
            "supplier_name": ext.supplier_name or "",
            "buyer_tax_id": ext.buyer_tax_id or "",
            "buyer_name": ext.buyer_name or "",
            "invoice_number": ext.invoice_number or "",
            "invoice_series": ext.invoice_series or "",
            "issue_date": ext.issue_date or "",
            "currency": ext.currency,
            "subtotal": str(ext.subtotal),
            "tax_total": str(ext.tax_total),
            "amount_payable": str(ext.amount_payable),
        }
        if not lines:
            lines = [
                {
                    "sku": line.sku or "",
                    "description": line.description,
                    "qty": str(line.qty),
                    "unit_price": str(line.unit_price),
                    "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                    "line_amount": str(line.line_amount),
                }
                for line in ext.lines
            ]
        cost = 0.0000

    # 3-Way Reconciliation with PO & GRN
    detected_discrepancies: List[str] = []
    po, receipts = get_demo_po_and_grn(header.get("supplier_tax_id"), case["case_id"])
    policy = TolerancePolicy(
        tenant_id=uuid.uuid4(),
        price_tolerance_pct=Decimal("0.02"),
        qty_tolerance_pct=Decimal("0.00"),
    )

    if lines:
        inv_lines = [
            InvoiceLine(
                line_no=idx,
                sku_ref=item["sku"],
                description=item["description"],
                qty=Decimal(item["qty"]),
                unit_price=Decimal(item["unit_price"]),
                tax_rate=Decimal(item["tax_rate"]) if item.get("tax_rate") else None,
                line_amount=Decimal(item["line_amount"]),
            )
            for idx, item in enumerate(lines, start=1)
        ]
        invoice_agg = InvoiceAggregate(
            id=uuid.uuid4(),
            tenant_id=po.tenant_id,
            document_id=uuid.uuid4(),
            supplier_tax_id=header.get("supplier_tax_id"),
            invoice_number=header.get("invoice_number"),
            lines=inv_lines,
        )
        engine = MatchingEngine()
        report = engine.match_3_way(invoice_agg, po=po, receipts=receipts, policy=policy)
        for issue in report.issues:
            if "PRICE" in issue.code:
                detected_discrepancies.append("PRICE_MISMATCH")
            elif "QUANTITY" in issue.code or "QTY" in issue.code:
                detected_discrepancies.append("QUANTITY_MISMATCH")

    duration_ms = (time.perf_counter() - start) * 1000
    return {
        "case_id": case["case_id"],
        "baseline_id": "B5_INVOICEFLOW_HYBRID",
        "header": header,
        "lines": lines,
        "detected_discrepancies": detected_discrepancies,
        "latency_ms": round(duration_ms, 2),
        "cost_usd": cost,
    }


async def run_benchmark_async() -> Dict[str, Any]:
    cases = load_manifest()
    settings = get_settings()
    adapter = OpenAIAdapter(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        model_id=settings.OPENAI_MODEL_ID,
        timeout=5.0,
        max_retries=0,
    )

    has_api_key = bool(adapter.api_key and adapter.api_key != "mock-key")
    report: Dict[str, Any] = {
        "benchmark_suite": "InvoiceFlow AI Frozen AP Benchmark v1.0",
        "total_cases": len(cases),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_id": settings.OPENAI_MODEL_ID,
        "live_ai_enabled": has_api_key,
        "baselines": {},
    }

    results_dir = ROOT_DIR / "benchmarks" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    all_predictions = []

    # Run B0
    print("[*] Running Baseline B0: XML Direct Extraction...", flush=True)
    b0_scores = []
    for c in cases:
        p = get_fixture_file(c["case_id"])
        pred = run_b0_xml_direct(c, p)
        ev = evaluate_prediction(c, pred)
        b0_scores.append(ev)
        all_predictions.append(
            {
                "case_id": c["case_id"],
                "baseline": "B0_XML_DIRECT",
                "prediction": pred,
                "evaluation": ev,
            }
        )

    # Run B1
    print("[*] Running Baseline B1: PyMuPDF Layout + Heuristics...", flush=True)
    b1_scores = []
    for c in cases:
        p = get_fixture_file(c["case_id"])
        pred = run_b1_pymupdf_rules(c, p)
        ev = evaluate_prediction(c, pred)
        b1_scores.append(ev)
        all_predictions.append(
            {
                "case_id": c["case_id"],
                "baseline": "B1_PYMUPDF_RULES",
                "prediction": pred,
                "evaluation": ev,
            }
        )

    # Run B2
    print("[*] Running Baseline B2: Docling Native Text + Heuristics...", flush=True)
    b2_scores = []
    for c in cases:
        p = get_fixture_file(c["case_id"])
        pred = run_b2_docling_text_rules(c, p)
        ev = evaluate_prediction(c, pred)
        b2_scores.append(ev)
        all_predictions.append(
            {
                "case_id": c["case_id"],
                "baseline": "B2_DOCLING_TEXT_RULES",
                "prediction": pred,
                "evaluation": ev,
            }
        )

    # Run B3
    print("[*] Running Baseline B3: Docling OCR + Structure-Aware Table Extraction...", flush=True)
    b3_scores = []
    for c in cases:
        p = get_fixture_file(c["case_id"])
        pred = run_b3_docling_ocr_structured(c, p)
        ev = evaluate_prediction(c, pred)
        b3_scores.append(ev)
        all_predictions.append(
            {
                "case_id": c["case_id"],
                "baseline": "B3_DOCLING_OCR_STRUCTURED",
                "prediction": pred,
                "evaluation": ev,
            }
        )

    # Run B4
    mode_str = (
        f"Live AI via {settings.OPENAI_MODEL_ID}" if has_api_key else "Offline CI Fallback (No Key)"
    )
    print(f"[*] Running Baseline B4: Pure Vision LLM ({mode_str})...", flush=True)
    b4_scores = []
    for c in cases:
        p = get_fixture_file(c["case_id"])
        pred = await run_b4_pure_vision_llm(c, p, adapter)
        ev = evaluate_prediction(c, pred)
        b4_scores.append(ev)
        all_predictions.append(
            {
                "case_id": c["case_id"],
                "baseline": "B4_PURE_VISION_LLM",
                "prediction": pred,
                "evaluation": ev,
            }
        )

    # Run B5
    print(
        "[*] Running Baseline B5: InvoiceFlow AI Hybrid Pipeline (Routing + Docling/OCR + Table Extractor + 3-Way Match)...",
        flush=True,
    )
    b5_scores = []
    for c in cases:
        p = get_fixture_file(c["case_id"])
        pred = await run_b5_invoiceflow_hybrid(c, p, adapter)
        ev = evaluate_prediction(c, pred)
        b5_scores.append(ev)
        all_predictions.append(
            {
                "case_id": c["case_id"],
                "baseline": "B5_INVOICEFLOW_HYBRID",
                "prediction": pred,
                "evaluation": ev,
            }
        )

    baseline_results = {
        "B0_XML_DIRECT": b0_scores,
        "B1_PYMUPDF_RULES": b1_scores,
        "B2_DOCLING_TEXT_RULES": b2_scores,
        "B3_DOCLING_OCR_STRUCTURED": b3_scores,
        "B4_PURE_VISION_LLM": b4_scores,
        "B5_INVOICEFLOW_HYBRID": b5_scores,
    }

    for b_id, case_scores in baseline_results.items():
        n = len(case_scores)
        avg_header_em = sum(s["header_exact_match"] for s in case_scores) / n
        avg_lines_f1 = sum(s["lines_f1"] for s in case_scores) / n
        avg_table_f1 = sum(s["table_f1"] for s in case_scores) / n
        avg_arith_valid = average_arithmetic_validity(case_scores)
        avg_anomaly_f1 = sum(s["anomaly_f1"] for s in case_scores) / n
        avg_latency = sum(s["latency_ms"] for s in case_scores) / n
        avg_cost_doc = sum(s["cost_usd"] for s in case_scores) / n
        cost_per_1k = avg_cost_doc * 1000
        arith_valid_pct = f"{avg_arith_valid * 100:.1f}%" if avg_arith_valid is not None else "N/A"

        report["baselines"][b_id] = {
            "header_exact_match": round(avg_header_em, 4),
            "lines_f1": round(avg_lines_f1, 4),
            "table_f1": round(avg_table_f1, 4),
            "arithmetic_validity_rate": round(avg_arith_valid, 4)
            if avg_arith_valid is not None
            else None,
            "anomaly_f1": round(avg_anomaly_f1, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "avg_cost_usd": round(avg_cost_doc, 6),
            "cost_per_1000_invoices_usd": round(cost_per_1k, 3),
        }

        summary_rows.append(
            {
                "Baseline": b_id,
                "Header Exact Match (%)": f"{avg_header_em * 100:.1f}%",
                "Line Items F1 (%)": f"{avg_lines_f1 * 100:.1f}%",
                "Table F1 (%)": f"{avg_table_f1 * 100:.1f}%",
                "Arithmetic Validity (%)": arith_valid_pct,
                "Anomaly F1 (%)": f"{avg_anomaly_f1 * 100:.1f}%",
                "Avg Latency (ms)": f"{avg_latency:.1f}",
                "Cost / 1K Invoices ($)": f"${cost_per_1k:.2f}",
            }
        )

    report_file = results_dir / "benchmark_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    csv_file = results_dir / "benchmark_summary.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    predictions_file = results_dir / "predictions.jsonl"
    with open(predictions_file, "w", encoding="utf-8") as f:
        for item in all_predictions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return report


def main() -> None:
    print("=" * 70)
    print(" InvoiceFlow AI - Real Document Benchmark Execution")
    print("=" * 70)
    report = asyncio.run(run_benchmark_async())

    print(f"\nEvaluated on {report['total_cases']} real document fixtures.")
    print("-" * 70)
    print(
        f"{'Baseline':<27} | {'Header EM':<10} | {'Table F1':<10} | {'Arith Valid':<11} | {'Latency':<10} | {'Cost/1k'}"
    )
    print("-" * 70)
    for b_id, stats in report["baselines"].items():
        em = f"{stats['header_exact_match'] * 100:.1f}%"
        tf1 = f"{stats['table_f1'] * 100:.1f}%"
        ar = (
            f"{stats['arithmetic_validity_rate'] * 100:.1f}%"
            if stats["arithmetic_validity_rate"] is not None
            else "N/A"
        )
        lat = f"{stats['avg_latency_ms']:.1f}ms"
        cost = f"${stats['cost_per_1000_invoices_usd']:.2f}"
        print(f"{b_id:<27} | {em:<10} | {tf1:<10} | {ar:<11} | {lat:<10} | {cost}")
    print("-" * 70)
    print("Results saved to benchmarks/results/benchmark_report.json")


if __name__ == "__main__":
    main()
