from decimal import Decimal
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List
import uuid
import fitz
import pytest
from sqlalchemy import select

from invoiceflow.application.ingestion.preflight import IngestionPreflight
from invoiceflow.application.ingestion.service import IngestionService
from invoiceflow.application.processing.coordinator import JobCoordinator
from invoiceflow.application.review.service import ReviewService
from invoiceflow.infrastructure.database.models import (
    FieldEvidenceORM,
    InvoiceLineORM,
    InvoiceORM,
    ProcessingJobORM,
)
from invoiceflow.infrastructure.database.repositories import InvoiceRepository
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.xml_parser import SecureXMLParser
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter
from invoiceflow.infrastructure.storage.exporter import DocumentExporter
from invoiceflow.infrastructure.storage.service import LocalStorageService

_UNICODE_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
_FONT_ALIAS = "vnfont"


def _resolve_font_path() -> str:
    for candidate in _UNICODE_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return ""


def _draw_text(page: fitz.Page, point: tuple[float, float], text: str, fontsize: float = 9) -> None:
    font_path = _resolve_font_path()
    if font_path:
        try:
            page.insert_text(point, text, fontsize=fontsize, fontname=_FONT_ALIAS)
            return
        except Exception:
            pass
    page.insert_text(point, text, fontsize=fontsize)


def _prepare_page_font(page: fitz.Page) -> None:
    font_path = _resolve_font_path()
    if font_path:
        try:
            page.insert_font(fontname=_FONT_ALIAS, fontfile=font_path)
        except Exception:
            pass


def generate_diverse_invoice_pdf(
    out_path: Path,
    spec: Dict[str, Any],
    is_scan: bool = False,
    is_borderless: bool = False,
    rotate_deg: int = 0,
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _prepare_page_font(page)

    _draw_text(page, (170, 50), "HOA DON GIA TRI GIA TANG", fontsize=16)
    _draw_text(page, (215, 70), "(ELECTRONIC INVOICE)", fontsize=10)

    _draw_text(page, (50, 110), f"Ky hieu (Series): {spec['series']}")
    _draw_text(page, (350, 110), f"So (Invoice No): {spec['invoice_no']}")
    _draw_text(page, (50, 130), f"Ngay (Date): {spec['date_str']}")
    _draw_text(page, (350, 130), "Tien te (Currency): VND")

    _draw_text(page, (50, 160), f"Don vi ban (Supplier): {spec['supplier_name']}")
    _draw_text(page, (50, 180), f"Ma so thue (Tax ID): {spec['supplier_tax_id']}")

    _draw_text(page, (50, 210), f"Don vi mua (Buyer): {spec['buyer_name']}")
    _draw_text(page, (50, 230), f"Ma so thue (Tax ID): {spec['buyer_tax_id']}")

    y_table = 260
    if not is_borderless:
        page.draw_rect(
            fitz.Rect(50, y_table, 545, y_table + 25),
            fill=(0.92, 0.92, 0.92),
            color=(0.5, 0.5, 0.5),
        )
    _draw_text(page, (55, y_table + 17), "STT", fontsize=9)
    _draw_text(page, (85, y_table + 17), "Ten hang hoa, dich vu / SKU", fontsize=9)
    _draw_text(page, (310, y_table + 17), "So luong", fontsize=9)
    _draw_text(page, (370, y_table + 17), "Don gia", fontsize=9)
    _draw_text(page, (440, y_table + 17), "Thue suat", fontsize=9)
    _draw_text(page, (480, y_table + 17), "Thanh tien", fontsize=9)

    curr_y = y_table + 25
    for idx, item in enumerate(spec["lines"], start=1):
        if not is_borderless:
            page.draw_rect(fitz.Rect(50, curr_y, 545, curr_y + 26), color=(0.75, 0.75, 0.75))
        _draw_text(page, (55, curr_y + 17), str(idx), fontsize=9)
        sku_str = f" [{item['sku']}]" if item.get("sku") else ""
        _draw_text(page, (85, curr_y + 17), f"{item['desc']}{sku_str}", fontsize=9)
        _draw_text(page, (310, curr_y + 17), str(item["qty"]), fontsize=9)
        _draw_text(page, (370, curr_y + 17), str(item["unit_price"]), fontsize=9)
        _draw_text(page, (440, curr_y + 17), f"{item['tax_rate']}%", fontsize=9)
        _draw_text(page, (480, curr_y + 17), str(item["line_amount"]), fontsize=9)
        curr_y += 26

    curr_y += 20
    _draw_text(page, (350, curr_y), f"Cong tien hang (Subtotal): {spec['subtotal']}")
    _draw_text(page, (350, curr_y + 20), f"Tien thue GTGT (Tax Total): {spec['tax_total']}")
    _draw_text(page, (350, curr_y + 40), f"Tong cong (Total Amount): {spec['total']}")

    if is_scan:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        doc.close()

        scan_doc = fitz.open()
        scan_page = scan_doc.new_page(width=595, height=842)
        if rotate_deg != 0:
            scan_page.set_rotation(rotate_deg)
        scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)
        scan_doc.subset_fonts()
        scan_doc.save(str(out_path), deflate=True, deflate_images=True, garbage=4)
        scan_doc.close()
    else:
        doc.subset_fonts()
        doc.save(str(out_path), deflate=True, deflate_images=True, garbage=4)
        doc.close()


DIVERSE_DATASET: List[Dict[str, Any]] = [
    {
        "id": "INV-DIV-01",
        "series": "1C26TAA",
        "invoice_no": "0001001",
        "date_str": "2026-03-01",
        "supplier_tax_id": "0101234567",
        "supplier_name": "Công ty TNHH Phân phối Thiết bị Tin học Hà Nội",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "LAP-DELL-5520",
                "desc": "Laptop Dell Precision 5520 Core i7",
                "qty": "1.0000",
                "unit_price": "28000000.0000",
                "tax_rate": "8.00",
                "line_amount": "28000000.0000",
            },
        ],
        "subtotal": "28000000.0000",
        "tax_total": "2240000.0000",
        "total": "30240000.0000",
    },
    {
        "id": "INV-DIV-02",
        "series": "1C26TBB",
        "invoice_no": "0001002",
        "date_str": "2026-03-02",
        "supplier_tax_id": "0309876543",
        "supplier_name": "Công ty CP Giấy & Văn phòng phẩm Miền Nam",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "PAPER-A4-80",
                "desc": "Giấy photocopy Double A A4 80gsm",
                "qty": "100.0000",
                "unit_price": "75000.0000",
                "tax_rate": "10.00",
                "line_amount": "7500000.0000",
            },
            {
                "sku": "PEN-BALL-BL",
                "desc": "Bút bi Thiên Long xanh 0.5mm",
                "qty": "50.0000",
                "unit_price": "5000.0000",
                "tax_rate": "10.00",
                "line_amount": "250000.0000",
            },
        ],
        "subtotal": "7750000.0000",
        "tax_total": "775000.0000",
        "total": "8525000.0000",
    },
    {
        "id": "INV-DIV-03",
        "series": "1C26TCC",
        "invoice_no": "0001003",
        "date_str": "2026-03-03",
        "supplier_tax_id": "0105554321",
        "supplier_name": "Công ty TNHH Vệ sinh & Bảo trì Công nghiệp",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": True,
        "lines": [
            {
                "sku": "SERV-CLEAN-01",
                "desc": "Dịch vụ vệ sinh công nghiệp sàn văn phòng quý 1",
                "qty": "1.0000",
                "unit_price": "12000000.0000",
                "tax_rate": "8.00",
                "line_amount": "12000000.0000",
            },
        ],
        "subtotal": "12000000.0000",
        "tax_total": "960000.0000",
        "total": "12960000.0000",
    },
    {
        "id": "INV-DIV-04",
        "series": "1C26TDD",
        "invoice_no": "0001004",
        "date_str": "2026-03-04",
        "supplier_tax_id": "0101112222",
        "supplier_name": "Tập đoàn Công nghệ Viễn thông Quốc tế VN",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "NET-LEASED-100M",
                "desc": "Cước dịch vụ Internet cáp quang Leased Line 100Mbps",
                "qty": "1.0000",
                "unit_price": "8500000.0000",
                "tax_rate": "10.00",
                "line_amount": "8500000.0000",
            },
        ],
        "subtotal": "8500000.0000",
        "tax_total": "850000.0000",
        "total": "9350000.0000",
    },
    {
        "id": "INV-DIV-05",
        "series": "1C26TEE",
        "invoice_no": "0001005",
        "date_str": "2026-03-05",
        "supplier_tax_id": "0304445555",
        "supplier_name": "Công ty TNHH Dịch vụ Đám mây & Máy chủ Việt",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": True,
        "lines": [
            {
                "sku": "CLOUD-VM-PRO",
                "desc": "Thuê máy chủ ảo Cloud VPS 8 Core 32GB RAM",
                "qty": "3.0000",
                "unit_price": "2500000.0000",
                "tax_rate": "10.00",
                "line_amount": "7500000.0000",
            },
        ],
        "subtotal": "7500000.0000",
        "tax_total": "750000.0000",
        "total": "8250000.0000",
    },
    {
        "id": "INV-DIV-06",
        "series": "1C26TFF",
        "invoice_no": "0001006",
        "date_str": "2026-03-06",
        "supplier_tax_id": "0107778888",
        "supplier_name": "Công ty Cổ phần Thiết kế Nội thất Văn phòng Hiện đại",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "CHAIR-ERG-01",
                "desc": "Ghế xoay công thái học Ergonomic lưới cao cấp",
                "qty": "10.0000",
                "unit_price": "3500000.0000",
                "tax_rate": "8.00",
                "line_amount": "35000000.0000",
            },
            {
                "sku": "DESK-STAND-12",
                "desc": "Bàn làm việc nâng hạ tự động motor đôi",
                "qty": "5.0000",
                "unit_price": "6000000.0000",
                "tax_rate": "8.00",
                "line_amount": "30000000.0000",
            },
        ],
        "subtotal": "65000000.0000",
        "tax_total": "5200000.0000",
        "total": "70200000.0000",
    },
    {
        "id": "INV-DIV-07",
        "series": "1C26TGG",
        "invoice_no": "0001007",
        "date_str": "2026-03-07",
        "supplier_tax_id": "0301239876",
        "supplier_name": "Công ty TNHH Vận tải & Logistics Toàn Cầu",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "SHIP-CONT-40",
                "desc": "Cước vận chuyển container 40 feet tuyến Hải Phòng - TP HCM",
                "qty": "2.0000",
                "unit_price": "18000000.0000",
                "tax_rate": "8.00",
                "line_amount": "36000000.0000",
            },
            {
                "sku": "FEE-CUSTOMS",
                "desc": "Phí nâng hạ và thủ tục khai báo hải quan nội địa",
                "qty": "2.0000",
                "unit_price": "1500000.0000",
                "tax_rate": "8.00",
                "line_amount": "3000000.0000",
            },
        ],
        "subtotal": "39000000.0000",
        "tax_total": "3120000.0000",
        "total": "42120000.0000",
    },
    {
        "id": "INV-DIV-08",
        "series": "1C26THH",
        "invoice_no": "0001008",
        "date_str": "2026-03-08",
        "supplier_tax_id": "0103339999",
        "supplier_name": "Công ty TNHH Tư vấn & Đào tạo Doanh nghiệp Chuẩn",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": True,
        "lines": [
            {
                "sku": "TRAIN-SEMINAR",
                "desc": "Khóa đào tạo quản lý tài chính doanh nghiệp nâng cao",
                "qty": "1.0000",
                "unit_price": "15000000.0000",
                "tax_rate": "10.00",
                "line_amount": "15000000.0000",
            },
        ],
        "subtotal": "15000000.0000",
        "tax_total": "1500000.0000",
        "total": "16500000.0000",
    },
    {
        "id": "INV-DIV-09",
        "series": "1C26TII",
        "invoice_no": "0001009",
        "date_str": "2026-03-09",
        "supplier_tax_id": "0106665555",
        "supplier_name": "Công ty Cổ phần Thực phẩm & Dịch vụ Ẩm thực Thủ Đô",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "BUFFET-VIP",
                "desc": "Tiệc liên hoan gặp mặt khách hàng đầu năm VIP",
                "qty": "20.0000",
                "unit_price": "650000.0000",
                "tax_rate": "8.00",
                "line_amount": "13000000.0000",
            },
        ],
        "subtotal": "13000000.0000",
        "tax_total": "1040000.0000",
        "total": "14040000.0000",
    },
    {
        "id": "INV-DIV-10",
        "series": "1C26TJJ",
        "invoice_no": "0001010",
        "date_str": "2026-03-10",
        "supplier_tax_id": "0305551111",
        "supplier_name": "Công ty TNHH Vật tư & Thiết bị Y tế Đông Á",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "MED-MASK-N95",
                "desc": "Khẩu trang bảo hộ chuyên dụng kháng khuẩn N95",
                "qty": "500.0000",
                "unit_price": "12000.0000",
                "tax_rate": "5.00",
                "line_amount": "6000000.0000",
            },
            {
                "sku": "MED-GLOVE-NIT",
                "desc": "Găng tay y tế Nitrile không bột hộp 100 chiếc",
                "qty": "50.0000",
                "unit_price": "110000.0000",
                "tax_rate": "5.00",
                "line_amount": "5500000.0000",
            },
        ],
        "subtotal": "11500000.0000",
        "tax_total": "575000.0000",
        "total": "12075000.0000",
    },
    {
        "id": "INV-DIV-11",
        "series": "1C26TKK",
        "invoice_no": "0001011",
        "date_str": "2026-03-11",
        "supplier_tax_id": "0108882222",
        "supplier_name": "Công ty CP Thép Xây dựng & Kết cấu Tiền chế An Phú",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "STEEL-D16-CB",
                "desc": "Thép cuộn tròn trơn phi 16 tiêu chuẩn CB400",
                "qty": "5.0000",
                "unit_price": "16500000.0000",
                "tax_rate": "10.00",
                "line_amount": "82500000.0000",
            },
        ],
        "subtotal": "82500000.0000",
        "tax_total": "8250000.0000",
        "total": "90750000.0000",
    },
    {
        "id": "INV-DIV-12",
        "series": "1C26TLL",
        "invoice_no": "0001012",
        "date_str": "2026-03-12",
        "supplier_tax_id": "0104443333",
        "supplier_name": "Công ty TNHH Phát triển Phần mềm Doanh nghiệp Trí Tuệ",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": True,
        "lines": [
            {
                "sku": "LIC-ERP-USER",
                "desc": "Bản quyền phần mềm kế toán quản trị ERP người dùng",
                "qty": "10.0000",
                "unit_price": "4200000.0000",
                "tax_rate": "10.00",
                "line_amount": "42000000.0000",
            },
        ],
        "subtotal": "42000000.0000",
        "tax_total": "4200000.0000",
        "total": "46200000.0000",
    },
    {
        "id": "INV-DIV-13",
        "series": "1C26TMM",
        "invoice_no": "0001013",
        "date_str": "2026-03-13",
        "supplier_tax_id": "0309991234",
        "supplier_name": "Công ty CP Cơ điện Lạnh & Hệ thống Thông gió Miền Nam",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "AC-DAIKIN-24",
                "desc": "Máy điều hòa âm trần Daikin Inverter 24000BTU",
                "qty": "2.0000",
                "unit_price": "26000000.0000",
                "tax_rate": "10.00",
                "line_amount": "52000000.0000",
            },
        ],
        "subtotal": "52000000.0000",
        "tax_total": "5200000.0000",
        "total": "57200000.0000",
    },
    {
        "id": "INV-DIV-14",
        "series": "1C26TNN",
        "invoice_no": "0001014",
        "date_str": "2026-03-14",
        "supplier_tax_id": "0102227777",
        "supplier_name": "Công ty TNHH An toàn Thông tin & Bảo mật Số",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "SEC-AUDIT-PENTEST",
                "desc": "Dịch vụ đánh giá an ninh mạng và kiểm thử thâm nhập hệ thống",
                "qty": "1.0000",
                "unit_price": "45000000.0000",
                "tax_rate": "10.00",
                "line_amount": "45000000.0000",
            },
        ],
        "subtotal": "45000000.0000",
        "tax_total": "4500000.0000",
        "total": "49500000.0000",
    },
    {
        "id": "INV-DIV-15",
        "series": "1C26TOO",
        "invoice_no": "0001015",
        "date_str": "2026-03-15",
        "supplier_tax_id": "0101234567",
        "supplier_name": "Công ty TNHH Thiết bị Văn phòng Thăng Long",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "SRV-HPE-DL380",
                "desc": "Máy chủ doanh nghiệp HPE ProLiant DL380 Gen10",
                "qty": "1.0000",
                "unit_price": "95000000.0000",
                "tax_rate": "10.00",
                "line_amount": "95000000.0000",
            },
            {
                "sku": "RAM-REG-32GB",
                "desc": "Bộ nhớ máy chủ DDR4 32GB ECC Registered",
                "qty": "4.0000",
                "unit_price": "4500000.0000",
                "tax_rate": "10.00",
                "line_amount": "18000000.0000",
            },
        ],
        "subtotal": "113000000.0000",
        "tax_total": "11300000.0000",
        "total": "124300000.0000",
    },
    {
        "id": "INV-DIV-16",
        "series": "1C26TPP",
        "invoice_no": "0001016",
        "date_str": "2026-03-16",
        "supplier_tax_id": "0301119999",
        "supplier_name": "Công ty TNHH In ấn & Bao bì Thương phẩm Miền Đông",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "BOX-CARTON-5L",
                "desc": "Thùng carton 5 lớp sóng BC kích thước 60x40x40",
                "qty": "1000.0000",
                "unit_price": "18500.0000",
                "tax_rate": "8.00",
                "line_amount": "18500000.0000",
            },
        ],
        "subtotal": "18500000.0000",
        "tax_total": "1480000.0000",
        "total": "19980000.0000",
    },
    {
        "id": "INV-DIV-17",
        "series": "1C26TQQ",
        "invoice_no": "0001017",
        "date_str": "2026-03-17",
        "supplier_tax_id": "0109871111",
        "supplier_name": "Công ty CP Chiếu sáng & Thiết bị Đô thị",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": True,
        "lines": [
            {
                "sku": "LED-PANEL-6060",
                "desc": "Đèn LED Panel gắn trần văn phòng 600x600 48W",
                "qty": "40.0000",
                "unit_price": "320000.0000",
                "tax_rate": "8.00",
                "line_amount": "12800000.0000",
            },
        ],
        "subtotal": "12800000.0000",
        "tax_total": "1024000.0000",
        "total": "13824000.0000",
    },
    {
        "id": "INV-DIV-18",
        "series": "1C26TRR",
        "invoice_no": "0001018",
        "date_str": "2026-03-18",
        "supplier_tax_id": "0104567890",
        "supplier_name": "Công ty TNHH Cung ứng Hóa chất Công nghiệp Thăng Long",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "CHEM-ETHANOL-96",
                "desc": "Dung môi cồn Ethanol công nghiệp 96 độ phuy 200L",
                "qty": "5.0000",
                "unit_price": "4500000.0000",
                "tax_rate": "10.00",
                "line_amount": "22500000.0000",
            },
        ],
        "subtotal": "22500000.0000",
        "tax_total": "2250000.0000",
        "total": "24750000.0000",
    },
    {
        "id": "INV-DIV-19",
        "series": "1C26TSS",
        "invoice_no": "0001019",
        "date_str": "2026-03-19",
        "supplier_tax_id": "0306543210",
        "supplier_name": "Công ty Cổ phần Công nghệ Xanh Năng lượng Mặt trời",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": False,
        "is_borderless": False,
        "lines": [
            {
                "sku": "SOLAR-INV-10KW",
                "desc": "Biến tần năng lượng mặt trời hòa lưới Inverter 10kW",
                "qty": "1.0000",
                "unit_price": "28500000.0000",
                "tax_rate": "8.00",
                "line_amount": "28500000.0000",
            },
        ],
        "subtotal": "28500000.0000",
        "tax_total": "2280000.0000",
        "total": "30780000.0000",
    },
    {
        "id": "INV-DIV-20",
        "series": "1C26TTT",
        "invoice_no": "0001020",
        "date_str": "2026-03-20",
        "supplier_tax_id": "0105554321",
        "supplier_name": "Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội",
        "buyer_tax_id": "0109998888",
        "buyer_name": "Công ty Cổ phần Thương mại Alpha VN",
        "is_scan": True,
        "is_borderless": False,
        "rotate_deg": 0,
        "lines": [
            {
                "sku": "CLEAN-KIT-02",
                "desc": "Bộ dụng cụ vệ sinh văn phòng toàn diện cao cấp",
                "qty": "10.0000",
                "unit_price": "850000.0000",
                "tax_rate": "8.00",
                "line_amount": "8500000.0000",
            },
        ],
        "subtotal": "8500000.0000",
        "tax_total": "680000.0000",
        "total": "9180000.0000",
    },
]


def test_independent_field_extraction_on_diverse_digital_invoices():
    """Verify independent extraction of key financial fields across 19 diverse digital invoice layouts:
    Supplier Tax ID, Invoice No, Issue Date, Supplier Name, Buyer Name, SKU, Qty, Price, Line Total, Payable.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    parser = DigitalPDFParser()
    try:
        digital_cases = [spec for spec in DIVERSE_DATASET if not spec.get("is_scan")]
        assert len(digital_cases) >= 19

        for spec in digital_cases:
            pdf_path = tmp_dir / f"{spec['id']}.pdf"
            generate_diverse_invoice_pdf(
                pdf_path, spec, is_scan=False, is_borderless=spec.get("is_borderless", False)
            )

            doc = fitz.open(str(pdf_path))
            full_text = "\n".join(page.get_text() for page in doc)
            doc.close()

            extraction = parser.parse(full_text)

            assert extraction.supplier_tax_id == spec["supplier_tax_id"], (
                f"Supplier Tax ID mismatch in {spec['id']}"
            )
            assert extraction.buyer_tax_id == spec["buyer_tax_id"], (
                f"Buyer Tax ID mismatch in {spec['id']}"
            )
            assert extraction.invoice_number == spec["invoice_no"], (
                f"Invoice No mismatch in {spec['id']}"
            )
            assert extraction.invoice_series == spec["series"], f"Series mismatch in {spec['id']}"
            assert extraction.issue_date == spec["date_str"], f"Date mismatch in {spec['id']}"
            assert extraction.amount_payable == Decimal(spec["total"]), (
                f"Amount payable mismatch in {spec['id']}"
            )
            assert extraction.subtotal == Decimal(spec["subtotal"]), (
                f"Subtotal mismatch in {spec['id']}"
            )
            assert extraction.tax_total == Decimal(spec["tax_total"]), (
                f"Tax total mismatch in {spec['id']}"
            )

            assert len(extraction.lines) == len(spec["lines"]), (
                f"Line count mismatch in {spec['id']}"
            )
            for exp_item, got_line in zip(spec["lines"], extraction.lines):
                if exp_item.get("sku"):
                    assert got_line.sku == exp_item["sku"], f"SKU mismatch in {spec['id']}"
                assert got_line.qty == Decimal(exp_item["qty"])
                assert got_line.unit_price == Decimal(exp_item["unit_price"])
                assert got_line.line_amount == Decimal(exp_item["line_amount"])
                assert (got_line.qty * got_line.unit_price) == got_line.line_amount

            assert (extraction.subtotal + extraction.tax_total) == extraction.amount_payable

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_full_application_lifecycle_with_diverse_invoice():
    """Verify complete application lifecycle with a newly generated diverse invoice:
    Upload -> Ingestion -> ProcessingJob -> Document AI (Parsing & Evidence BBoxes) -> Review -> Approve -> Export.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    spec = DIVERSE_DATASET[1]  # INV-DIV-02: 2 lines with 10% VAT
    pdf_path = tmp_dir / f"{spec['id']}.pdf"
    generate_diverse_invoice_pdf(pdf_path, spec, is_scan=False, is_borderless=False)
    pdf_content = pdf_path.read_bytes()

    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    try:
        storage = LocalStorageService(base_dir=str(tmp_dir / "storage"))
        preflight = IngestionPreflight()
        tenant_id = str(uuid.uuid4())
        reviewer_id = str(uuid.uuid4())

        async with db_manager.session() as session:
            ingestion = IngestionService(session, storage, preflight)
            doc, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id,
                filename=f"{spec['id']}.pdf",
                content=pdf_content,
            )
            job_id = job.id

        coordinator = JobCoordinator(
            db_manager=db_manager,
            storage=storage,
            xml_parser=SecureXMLParser(),
            pdf_inspector=PDFInspector(),
            layout_extractor=LayoutExtractor(),
            llm_adapter=OpenAIAdapter(api_key=None),
        )
        success = await coordinator.process_job(job_id)
        assert success is True

        invoice_id = None
        current_revision = None
        async with db_manager.session() as session:
            job_orm = (
                await session.execute(select(ProcessingJobORM).where(ProcessingJobORM.id == job_id))
            ).scalar_one()
            assert job_orm.status == "READY_FOR_REVIEW"

            inv_repo = InvoiceRepository(session)
            invoices = await inv_repo.list_invoices(tenant_id=tenant_id)
            assert len(invoices) == 1
            inv = invoices[0]
            invoice_id = inv.id
            current_revision = inv.revision

            assert inv.invoice_number == spec["invoice_no"]
            assert inv.supplier_tax_id == spec["supplier_tax_id"]
            assert inv.amount_payable == Decimal(spec["total"])
            assert inv.status == "READY_FOR_REVIEW"

            lines_res = await session.execute(
                select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
            )
            lines = lines_res.scalars().all()
            assert len(lines) == 2
            assert lines[0].sku_ref == "PAPER-A4-80"
            assert lines[0].qty == Decimal("100.0000")
            assert lines[1].sku_ref == "PEN-BALL-BL"
            assert lines[1].qty == Decimal("50.0000")

            ev_res = await session.execute(
                select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == invoice_id)
            )
            evidences = ev_res.scalars().all()
            assert len(evidences) > 0
            assert any(e.field_path == "amount_payable" for e in evidences)

        async with db_manager.session() as session:
            review_svc = ReviewService(session)
            updated_inv = await review_svc.update_invoice_fields(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                expected_revision=current_revision,
                actor_id=reviewer_id,
                patches={"supplier_name": "Công ty CP Giấy & Văn phòng phẩm Miền Nam (Xác nhận)"},
                reason="Xác thực tên đơn vị bán hàng theo giấy phép kinh doanh",
            )
            assert updated_inv.revision == current_revision + 1
            current_revision = updated_inv.revision

        async with db_manager.session() as session:
            review_svc = ReviewService(session)
            approved_inv = await review_svc.approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                expected_revision=current_revision,
                actor_id=reviewer_id,
                notes="Phê duyệt thanh toán cho văn phòng phẩm",
            )
            assert approved_inv.status == "APPROVED"
            assert approved_inv.revision == current_revision + 1

        async with db_manager.session() as session:
            res = await session.execute(
                select(InvoiceORM).where(
                    InvoiceORM.tenant_id == tenant_id, InvoiceORM.status == "APPROVED"
                )
            )
            approved_list = res.scalars().all()
            assert len(approved_list) == 1

            export_data = [
                {
                    "id": i.id,
                    "supplier_name": i.supplier_name or "",
                    "supplier_tax_id": i.supplier_tax_id or "",
                    "invoice_number": i.invoice_number or "",
                    "invoice_series": i.invoice_series or "",
                    "issue_date": i.issue_date.isoformat() if i.issue_date else "",
                    "currency": i.currency,
                    "subtotal": Decimal(str(i.subtotal)),
                    "tax_total": Decimal(str(i.tax_total)),
                    "amount_payable": Decimal(str(i.amount_payable)),
                    "status": i.status,
                }
                for i in approved_list
            ]

            csv_data = DocumentExporter.to_csv(export_data)
            assert spec["invoice_no"] in csv_data
            assert spec["supplier_tax_id"] in csv_data

            json_data = DocumentExporter.to_json(export_data)
            parsed = json.loads(json_data)
            assert len(parsed) == 1
            assert parsed[0]["invoice_number"] == spec["invoice_no"]
            assert parsed[0]["status"] == "APPROVED"

            excel_data = DocumentExporter.to_excel(export_data)
            assert len(excel_data) > 0
            assert excel_data[:4] == b"PK\x03\x04"

    finally:
        await db_manager.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
