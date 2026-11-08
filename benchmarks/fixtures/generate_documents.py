import fitz
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent / "documents"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

_UNICODE_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

_FONT_ALIAS = "vnfont"


def _resolve_unicode_font_path() -> str:
    for candidate in _UNICODE_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError(
        "No Unicode-capable TTF font found for Vietnamese fixture generation. "
        f"Checked: {_UNICODE_FONT_CANDIDATES}"
    )


def _prepare_unicode_font(page: "fitz.Page") -> None:
    # PyMuPDF's Base-14 fonts (e.g. "helv") do not carry a correct ToUnicode CMap
    # for Vietnamese combining diacritics, which corrupts both text-layer
    # extraction and the rasterized glyph shapes used as OCR input. Embedding a
    # real Unicode TTF keeps round-trip text extraction faithful to the source.
    page.insert_font(fontname=_FONT_ALIAS, fontfile=_resolve_unicode_font_path())


def _text(page: "fitz.Page", point: tuple[float, float], text: str, fontsize: float = 10) -> None:
    page.insert_text(point, text, fontsize=fontsize, fontname=_FONT_ALIAS)


def _save(doc: "fitz.Document", out_path: Path) -> None:
    # Without this, PyMuPDF embeds the full (unsubsetted) TTF font and
    # stores inserted raster images uncompressed, inflating a few KB of
    # real content into an 11+ MB fixture file.
    doc.subset_fonts()
    doc.save(str(out_path), deflate=True, deflate_images=True, garbage=4)


def create_digital_pdf(
    filename: str,
    invoice_no: str,
    series: str,
    date_str: str,
    supplier_tax_id: str,
    supplier_name: str,
    buyer_tax_id: str,
    buyer_name: str,
    sku: str,
    desc: str,
    qty: str,
    unit_price: str,
    tax_rate: str,
    subtotal: str,
    tax_total: str,
    total: str,
):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    _prepare_unicode_font(page)

    # Header title
    _text(page, (180, 50), "HOA DON GIA TRI GIA TANG", fontsize=16)
    _text(page, (210, 70), "(ELECTRONIC INVOICE)", fontsize=10)

    # Metadata
    _text(page, (50, 110), f"Ky hieu (Series): {series}")
    _text(page, (350, 110), f"So (Invoice No): {invoice_no}")
    _text(page, (50, 130), f"Ngay (Date): {date_str}")
    _text(page, (350, 130), "Tien te (Currency): VND")

    # Supplier info
    _text(page, (50, 160), f"Don vi ban (Supplier): {supplier_name}")
    _text(page, (50, 180), f"Ma so thue (Tax ID): {supplier_tax_id}")

    # Buyer info
    _text(page, (50, 210), f"Don vi mua (Buyer): {buyer_name}")
    _text(page, (50, 230), f"Ma so thue (Tax ID): {buyer_tax_id}")

    # Line item table headers
    page.draw_rect(fitz.Rect(50, 260, 545, 285), fill=(0.9, 0.9, 0.9), color=(0.5, 0.5, 0.5))
    _text(page, (55, 277), "STT", fontsize=9)
    _text(page, (85, 277), "Ten hang hoa, dich vu / SKU", fontsize=9)
    _text(page, (310, 277), "So luong", fontsize=9)
    _text(page, (370, 277), "Don gia", fontsize=9)
    _text(page, (440, 277), "Thue suat", fontsize=9)
    _text(page, (480, 277), "Thanh tien", fontsize=9)

    # Line row
    page.draw_rect(fitz.Rect(50, 285, 545, 315), color=(0.7, 0.7, 0.7))
    _text(page, (55, 303), "1", fontsize=9)
    _text(page, (85, 303), f"{desc} [{sku}]", fontsize=9)
    _text(page, (310, 303), qty, fontsize=9)
    _text(page, (370, 303), unit_price, fontsize=9)
    _text(page, (440, 303), f"{tax_rate}%", fontsize=9)
    _text(page, (480, 303), subtotal, fontsize=9)

    # Totals
    _text(page, (350, 340), f"Cong tien hang (Subtotal): {subtotal}")
    _text(page, (350, 360), f"Tien thue GTGT (Tax Total): {tax_total}")
    _text(page, (350, 380), f"Tong cong (Total Amount): {total}")

    out_path = DOCS_DIR / filename
    _save(doc, out_path)
    doc.close()
    print(f"Created digital PDF: {out_path}")


def create_scanned_pdf(
    filename: str,
    invoice_no: str,
    series: str,
    date_str: str,
    supplier_tax_id: str,
    supplier_name: str,
    buyer_tax_id: str,
    buyer_name: str,
    sku: str,
    desc: str,
    qty: str,
    unit_price: str,
    tax_rate: str,
    subtotal: str,
    tax_total: str,
    total: str,
):
    # Step 1: create a temporary doc with text
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=595, height=842)
    _prepare_unicode_font(temp_page)
    _text(temp_page, (160, 60), "HOA DON BAN HANG (SCAN)", fontsize=16)
    _text(temp_page, (50, 110), f"Ky hieu: {series}  So: {invoice_no}  Ngay: {date_str}")
    _text(temp_page, (50, 140), f"Ben ban: {supplier_name} - MST: {supplier_tax_id}")
    _text(temp_page, (50, 170), f"Ben mua: {buyer_name} - MST: {buyer_tax_id}")
    _text(temp_page, (50, 210), f"Hang hoa: {desc} [{sku}]")
    _text(temp_page, (50, 230), f"So luong: {qty}  Don gia: {unit_price}  Thue: {tax_rate}%")
    _text(
        temp_page,
        (50, 260),
        f"Tien hang: {subtotal}  Thue GTGT: {tax_total}  Tong cong: {total}",
    )

    # Render to image pixmap at a realistic scan resolution
    pix = temp_page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    temp_doc.close()

    # Step 2: create new PDF with ONLY the image, no text layer
    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=595, height=842)
    scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)

    out_path = DOCS_DIR / filename
    _save(scan_doc, out_path)
    scan_doc.close()
    print(f"Created scanned PDF (image-only): {out_path}")


def create_multi_line_pdf(
    filename: str,
    invoice_no: str,
    series: str,
    date_str: str,
    supplier_tax_id: str,
    supplier_name: str,
    buyer_tax_id: str,
    buyer_name: str,
    lines: list[dict[str, str]],
    subtotal: str,
    tax_total: str,
    total: str,
):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _prepare_unicode_font(page)

    _text(page, (180, 50), "HOA DON GIA TRI GIA TANG", fontsize=16)
    _text(page, (210, 70), "(ELECTRONIC INVOICE)", fontsize=10)

    _text(page, (50, 110), f"Ky hieu (Series): {series}")
    _text(page, (350, 110), f"So (Invoice No): {invoice_no}")
    _text(page, (50, 130), f"Ngay (Date): {date_str}")
    _text(page, (350, 130), "Tien te (Currency): VND")

    _text(page, (50, 160), f"Don vi ban (Supplier): {supplier_name}")
    _text(page, (50, 180), f"Ma so thue (Tax ID): {supplier_tax_id}")

    _text(page, (50, 210), f"Don vi mua (Buyer): {buyer_name}")
    _text(page, (50, 230), f"Ma so thue (Tax ID): {buyer_tax_id}")

    page.draw_rect(fitz.Rect(50, 260, 545, 285), fill=(0.9, 0.9, 0.9), color=(0.5, 0.5, 0.5))
    _text(page, (55, 277), "STT", fontsize=9)
    _text(page, (85, 277), "Ten hang hoa, dich vu / SKU", fontsize=9)
    _text(page, (310, 277), "So luong", fontsize=9)
    _text(page, (370, 277), "Don gia", fontsize=9)
    _text(page, (440, 277), "Thue suat", fontsize=9)
    _text(page, (480, 277), "Thanh tien", fontsize=9)

    y = 285
    for idx, item in enumerate(lines, start=1):
        page.draw_rect(fitz.Rect(50, y, 545, y + 25), color=(0.7, 0.7, 0.7))
        _text(page, (55, y + 17), str(idx), fontsize=9)
        _text(page, (85, y + 17), f"{item['desc']} [{item['sku']}]", fontsize=9)
        _text(page, (310, y + 17), str(item["qty"]), fontsize=9)
        _text(page, (370, y + 17), str(item["unit_price"]), fontsize=9)
        _text(page, (440, y + 17), f"{item['tax_rate']}%", fontsize=9)
        _text(page, (480, y + 17), str(item["line_amount"]), fontsize=9)
        y += 25

    y += 25
    _text(page, (350, y), f"Cong tien hang (Subtotal): {subtotal}")
    _text(page, (350, y + 20), f"Tien thue GTGT (Tax Total): {tax_total}")
    _text(page, (350, y + 40), f"Tong cong (Total Amount): {total}")

    out_path = DOCS_DIR / filename
    _save(doc, out_path)
    doc.close()
    print(f"Created multi-line digital PDF: {out_path}")


def create_rotated_scanned_pdf(
    filename: str,
    invoice_no: str,
    series: str,
    date_str: str,
    supplier_tax_id: str,
    supplier_name: str,
    buyer_tax_id: str,
    buyer_name: str,
    sku: str,
    desc: str,
    qty: str,
    unit_price: str,
    tax_rate: str,
    subtotal: str,
    tax_total: str,
    total: str,
    rotation: int = 90,
):
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=595, height=842)
    _prepare_unicode_font(temp_page)
    _text(temp_page, (160, 60), "HOA DON BAN HANG (ROTATED SCAN)", fontsize=16)
    _text(temp_page, (50, 110), f"Ky hieu: {series}  So: {invoice_no}  Ngay: {date_str}")
    _text(temp_page, (50, 140), f"Ben ban: {supplier_name} - MST: {supplier_tax_id}")
    _text(temp_page, (50, 170), f"Ben mua: {buyer_name} - MST: {buyer_tax_id}")
    _text(temp_page, (50, 210), f"Hang hoa: {desc} [{sku}]")
    _text(temp_page, (50, 230), f"So luong: {qty}  Don gia: {unit_price}  Thue: {tax_rate}%")
    _text(
        temp_page,
        (50, 260),
        f"Tien hang: {subtotal}  Thue GTGT: {tax_total}  Tong cong: {total}",
    )

    pix = temp_page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    temp_doc.close()

    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=595, height=842)
    scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)
    scan_page.set_rotation(rotation)

    out_path = DOCS_DIR / filename
    _save(scan_doc, out_path)
    scan_doc.close()
    print(f"Created rotated scanned PDF: {out_path}")


def create_scanned_table_pdf(
    filename: str,
    invoice_no: str,
    series: str,
    date_str: str,
    supplier_tax_id: str,
    supplier_name: str,
    buyer_tax_id: str,
    buyer_name: str,
    lines: list[dict[str, str]],
    subtotal: str,
    tax_total: str,
    total: str,
):
    # A multi-row line-item TABLE rendered as a pure image (no text layer),
    # so table-structure recognition genuinely has to run on OCR'd cells
    # rather than a digital text layer -- the other scan fixtures only have
    # flat paragraph text and never exercise this path.
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=595, height=842)
    _prepare_unicode_font(temp_page)
    _text(temp_page, (180, 50), "HOA DON GIA TRI GIA TANG", fontsize=16)
    _text(temp_page, (210, 70), "(ELECTRONIC INVOICE - SCAN)", fontsize=10)
    _text(temp_page, (50, 110), f"Ky hieu (Series): {series}")
    _text(temp_page, (350, 110), f"So (Invoice No): {invoice_no}")
    _text(temp_page, (50, 130), f"Ngay (Date): {date_str}")
    _text(temp_page, (50, 160), f"Don vi ban (Supplier): {supplier_name}")
    _text(temp_page, (50, 180), f"Ma so thue (Tax ID): {supplier_tax_id}")
    _text(temp_page, (50, 210), f"Don vi mua (Buyer): {buyer_name}")
    _text(temp_page, (50, 230), f"Ma so thue (Tax ID): {buyer_tax_id}")

    temp_page.draw_rect(fitz.Rect(50, 260, 545, 285), fill=(0.9, 0.9, 0.9), color=(0.5, 0.5, 0.5))
    _text(temp_page, (55, 277), "STT", fontsize=9)
    _text(temp_page, (85, 277), "Ten hang hoa, dich vu / SKU", fontsize=9)
    _text(temp_page, (310, 277), "So luong", fontsize=9)
    _text(temp_page, (370, 277), "Don gia", fontsize=9)
    _text(temp_page, (440, 277), "Thue suat", fontsize=9)
    _text(temp_page, (480, 277), "Thanh tien", fontsize=9)

    y = 285
    for idx, item in enumerate(lines, start=1):
        temp_page.draw_rect(fitz.Rect(50, y, 545, y + 25), color=(0.7, 0.7, 0.7))
        _text(temp_page, (55, y + 17), str(idx), fontsize=9)
        _text(temp_page, (85, y + 17), f"{item['desc']} [{item['sku']}]", fontsize=9)
        _text(temp_page, (310, y + 17), str(item["qty"]), fontsize=9)
        _text(temp_page, (370, y + 17), str(item["unit_price"]), fontsize=9)
        _text(temp_page, (440, y + 17), f"{item['tax_rate']}%", fontsize=9)
        _text(temp_page, (480, y + 17), str(item["line_amount"]), fontsize=9)
        y += 25

    y += 25
    _text(temp_page, (350, y), f"Cong tien hang (Subtotal): {subtotal}")
    _text(temp_page, (350, y + 20), f"Tien thue GTGT (Tax Total): {tax_total}")
    _text(temp_page, (350, y + 40), f"Tong cong (Total Amount): {total}")

    pix = temp_page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    temp_doc.close()

    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=595, height=842)
    scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)

    out_path = DOCS_DIR / filename
    _save(scan_doc, out_path)
    scan_doc.close()
    print(f"Created scanned table PDF (image-only): {out_path}")


def create_mixed_pdf(
    filename: str,
    invoice_no: str,
    series: str,
    date_str: str,
    supplier_tax_id: str,
    supplier_name: str,
    buyer_tax_id: str,
    buyer_name: str,
    sku: str,
    desc: str,
    qty: str,
    unit_price: str,
    tax_rate: str,
    subtotal: str,
    tax_total: str,
    total: str,
):
    # Page 1: native digital text layer. Page 2: scanned image attachment
    # (e.g. a delivery note photo) with no selectable text. Exercises the
    # DocumentRouter "mixed" classification branch end-to-end.
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    _prepare_unicode_font(page1)
    _text(page1, (180, 50), "HOA DON GIA TRI GIA TANG", fontsize=16)
    _text(page1, (50, 110), f"Ky hieu (Series): {series}")
    _text(page1, (350, 110), f"So (Invoice No): {invoice_no}")
    _text(page1, (50, 130), f"Ngay (Date): {date_str}")
    _text(page1, (50, 160), f"Don vi ban (Supplier): {supplier_name}")
    _text(page1, (50, 180), f"Ma so thue (Tax ID): {supplier_tax_id}")
    _text(page1, (50, 210), f"Don vi mua (Buyer): {buyer_name}")
    _text(page1, (50, 230), f"Ma so thue (Tax ID): {buyer_tax_id}")
    _text(page1, (85, 303), f"{desc} [{sku}]  SL: {qty}  Don gia: {unit_price}", fontsize=9)
    _text(page1, (350, 340), f"Cong tien hang (Subtotal): {subtotal}")
    _text(page1, (350, 360), f"Tien thue GTGT (Tax Total): {tax_total}")
    _text(page1, (350, 380), f"Tong cong (Total Amount): {total}")

    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=595, height=842)
    _prepare_unicode_font(temp_page)
    _text(temp_page, (160, 60), "PHIEU GIAO HANG DINH KEM (SCAN)", fontsize=14)
    _text(temp_page, (50, 120), f"Hang hoa: {desc} [{sku}]  So luong: {qty}")
    pix = temp_page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    temp_doc.close()

    page2 = doc.new_page(width=595, height=842)
    page2.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)

    out_path = DOCS_DIR / filename
    _save(doc, out_path)
    doc.close()
    print(f"Created mixed digital+scan PDF: {out_path}")


def main():
    # Case 2: Digital PDF
    create_digital_pdf(
        filename="case_02.pdf",
        invoice_no="0008890",
        series="1C26TBB",
        date_str="2026-03-05",
        supplier_tax_id="0309876543",
        supplier_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        sku="PAPER-A4-70",
        desc="Giấy photocopy Double A A4 70gsm",
        qty="200.0000",
        unit_price="60000.0000",
        tax_rate="8.00",
        subtotal="12000000.0000",
        tax_total="960000.0000",
        total="12960000.0000",
    )

    # Case 3: Scanned PDF (Pure Image, no selectable text)
    create_scanned_pdf(
        filename="case_03.pdf",
        invoice_no="0003412",
        series="2C26TCC",
        date_str="2026-03-08",
        supplier_tax_id="0105554321",
        supplier_name="Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        sku="CLEAN-SET-01",
        desc="Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng",
        qty="10.0000",
        unit_price="850000.0000",
        tax_rate="8.00",
        subtotal="8500000.0000",
        tax_total="680000.0000",
        total="9180000.0000",
    )

    # Case 4: Digital PDF with Price Discrepancy
    create_digital_pdf(
        filename="case_04.pdf",
        invoice_no="0008899",
        series="2C26TBB",
        date_str="2026-03-06",
        supplier_tax_id="0309876543",
        supplier_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        sku="PAPER-A4-70",
        desc="Giấy photocopy Double A A4 70gsm (lệch giá 5%)",
        qty="200.0000",
        unit_price="63000.0000",
        tax_rate="8.00",
        subtotal="12600000.0000",
        tax_total="1008000.0000",
        total="13608000.0000",
    )

    # Case 6: Multi-line Digital PDF with Table
    create_multi_line_pdf(
        filename="case_06.pdf",
        invoice_no="0005566",
        series="1C26TAA",
        date_str="2026-03-10",
        supplier_tax_id="0101234567",
        supplier_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        lines=[
            {
                "sku": "DELL-XPS-13",
                "desc": "Máy tính xách tay Dell XPS 13",
                "qty": "2.0000",
                "unit_price": "25000000.0000",
                "tax_rate": "10.00",
                "line_amount": "50000000.0000",
            },
            {
                "sku": "MOUSE-LOGI",
                "desc": "Chuột không dây Logitech MX Master 3S",
                "qty": "5.0000",
                "unit_price": "2000000.0000",
                "tax_rate": "10.00",
                "line_amount": "10000000.0000",
            },
            {
                "sku": "KEY-MECH-01",
                "desc": "Bàn phím cơ Keychron K2 Pro",
                "qty": "5.0000",
                "unit_price": "2000000.0000",
                "tax_rate": "10.00",
                "line_amount": "10000000.0000",
            },
        ],
        subtotal="70000000.0000",
        tax_total="7000000.0000",
        total="77000000.0000",
    )

    # Case 7: Rotated Scanned PDF (90 degrees)
    create_rotated_scanned_pdf(
        filename="case_07.pdf",
        invoice_no="0003499",
        series="2C26TCC",
        date_str="2026-03-12",
        supplier_tax_id="0105554321",
        supplier_name="Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        sku="CLEAN-SET-01",
        desc="Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng",
        qty="10.0000",
        unit_price="850000.0000",
        tax_rate="8.00",
        subtotal="8500000.0000",
        tax_total="680000.0000",
        total="9180000.0000",
        rotation=90,
    )

    # Case 8: Digital PDF with Vietnamese Thousand Separator Amounts
    create_digital_pdf(
        filename="case_08.pdf",
        invoice_no="0009100",
        series="1C26TBB",
        date_str="2026-03-15",
        supplier_tax_id="0309876543",
        supplier_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        sku="PAPER-A4-70",
        desc="Giấy photocopy Double A A4 70gsm",
        qty="200.0000",
        unit_price="60000.0000",
        tax_rate="8.00",
        subtotal="12000000.0000",
        tax_total="960000.0000",
        total="12960000.0000",
    )

    # Case 10: Scanned table PDF (pure image, multi-row line-item table)
    create_scanned_table_pdf(
        filename="case_10.pdf",
        invoice_no="0005599",
        series="1C26TAA",
        date_str="2026-03-20",
        supplier_tax_id="0101234567",
        supplier_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        lines=[
            {
                "sku": "DELL-XPS-13",
                "desc": "Máy tính xách tay Dell XPS 13",
                "qty": "2.0000",
                "unit_price": "25000000.0000",
                "tax_rate": "10.00",
                "line_amount": "50000000.0000",
            },
            {
                "sku": "MOUSE-LOGI",
                "desc": "Chuột không dây Logitech MX Master 3S",
                "qty": "5.0000",
                "unit_price": "2000000.0000",
                "tax_rate": "10.00",
                "line_amount": "10000000.0000",
            },
        ],
        subtotal="60000000.0000",
        tax_total="6000000.0000",
        total="66000000.0000",
    )

    # Case 9: Mixed PDF (digital page + attached scanned page)
    create_mixed_pdf(
        filename="case_09.pdf",
        invoice_no="0009977",
        series="1C26TBB",
        date_str="2026-03-18",
        supplier_tax_id="0309876543",
        supplier_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
        buyer_tax_id="0109998888",
        buyer_name="Công ty Cổ phần Thương mại Alpha VN",
        sku="PAPER-A4-70",
        desc="Giấy photocopy Double A A4 70gsm",
        qty="200.0000",
        unit_price="60000.0000",
        tax_rate="8.00",
        subtotal="12000000.0000",
        tax_total="960000.0000",
        total="12960000.0000",
    )


if __name__ == "__main__":
    main()
