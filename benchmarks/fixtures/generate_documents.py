import fitz
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent / "documents"
DOCS_DIR.mkdir(parents=True, exist_ok=True)


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

    # Header title
    page.insert_text((180, 50), "HOA DON GIA TRI GIA TANG", fontsize=16, fontname="helv")
    page.insert_text((210, 70), "(ELECTRONIC INVOICE)", fontsize=10, fontname="helv")

    # Metadata
    page.insert_text((50, 110), f"Ky hieu (Series): {series}", fontsize=10, fontname="helv")
    page.insert_text((350, 110), f"So (Invoice No): {invoice_no}", fontsize=10, fontname="helv")
    page.insert_text((50, 130), f"Ngay (Date): {date_str}", fontsize=10, fontname="helv")
    page.insert_text((350, 130), "Tien te (Currency): VND", fontsize=10, fontname="helv")

    # Supplier info
    page.insert_text((50, 160), f"Don vi ban (Supplier): {supplier_name}", fontsize=10, fontname="helv")
    page.insert_text((50, 180), f"Ma so thue (Tax ID): {supplier_tax_id}", fontsize=10, fontname="helv")

    # Buyer info
    page.insert_text((50, 210), f"Don vi mua (Buyer): {buyer_name}", fontsize=10, fontname="helv")
    page.insert_text((50, 230), f"Ma so thue (Tax ID): {buyer_tax_id}", fontsize=10, fontname="helv")

    # Line item table headers
    page.draw_rect(fitz.Rect(50, 260, 545, 285), fill=(0.9, 0.9, 0.9), color=(0.5, 0.5, 0.5))
    page.insert_text((55, 277), "STT", fontsize=9, fontname="helv")
    page.insert_text((85, 277), "Ten hang hoa, dich vu / SKU", fontsize=9, fontname="helv")
    page.insert_text((310, 277), "So luong", fontsize=9, fontname="helv")
    page.insert_text((370, 277), "Don gia", fontsize=9, fontname="helv")
    page.insert_text((440, 277), "Thue", fontsize=9, fontname="helv")
    page.insert_text((480, 277), "Thanh tien", fontsize=9, fontname="helv")

    # Line row
    page.draw_rect(fitz.Rect(50, 285, 545, 315), color=(0.7, 0.7, 0.7))
    page.insert_text((55, 303), "1", fontsize=9, fontname="helv")
    page.insert_text((85, 303), f"{desc} [{sku}]", fontsize=9, fontname="helv")
    page.insert_text((310, 303), qty, fontsize=9, fontname="helv")
    page.insert_text((370, 303), unit_price, fontsize=9, fontname="helv")
    page.insert_text((440, 303), f"{tax_rate}%", fontsize=9, fontname="helv")
    page.insert_text((480, 303), subtotal, fontsize=9, fontname="helv")

    # Totals
    page.insert_text((350, 340), f"Cong tien hang (Subtotal): {subtotal}", fontsize=10, fontname="helv")
    page.insert_text((350, 360), f"Tien thue GTGT (Tax Total): {tax_total}", fontsize=10, fontname="helv")
    page.insert_text((350, 380), f"Tong cong (Total Amount): {total}", fontsize=10, fontname="helv")

    out_path = DOCS_DIR / filename
    doc.save(str(out_path))
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
    temp_page.insert_text((160, 60), "HOA DON BAN HANG (SCAN)", fontsize=16, fontname="helv")
    temp_page.insert_text((50, 110), f"Ky hieu: {series}  So: {invoice_no}  Ngay: {date_str}", fontsize=10, fontname="helv")
    temp_page.insert_text((50, 140), f"Ben ban: {supplier_name} - MST: {supplier_tax_id}", fontsize=10, fontname="helv")
    temp_page.insert_text((50, 170), f"Ben mua: {buyer_name} - MST: {buyer_tax_id}", fontsize=10, fontname="helv")
    temp_page.insert_text((50, 210), f"Hang hoa: {desc} [{sku}]", fontsize=10, fontname="helv")
    temp_page.insert_text((50, 230), f"So luong: {qty}  Don gia: {unit_price}  Thue: {tax_rate}%", fontsize=10, fontname="helv")
    temp_page.insert_text((50, 260), f"Tien hang: {subtotal}  Thue GTGT: {tax_total}  Tong cong: {total}", fontsize=10, fontname="helv")

    # Render to image pixmap
    pix = temp_page.get_pixmap(dpi=96)
    img_bytes = pix.tobytes("png")
    temp_doc.close()

    # Step 2: create new PDF with ONLY the image, no text layer
    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=595, height=842)
    scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)

    out_path = DOCS_DIR / filename
    scan_doc.save(str(out_path))
    scan_doc.close()
    print(f"Created scanned PDF (image-only): {out_path}")


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


if __name__ == "__main__":
    main()
