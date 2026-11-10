"""Generator for realistic evaluation dataset with diverse suppliers, layouts, and capture conditions.

Generates:
- Public sample invoices (EVN, VNPT, Petrolimex).
- Augmented mobile photos (perspective distortion, shadows, wrinkles, complex background, rotation).
- Multi-page and multi-line invoices.
Also compiles the ground truth manifest benchmarks/fixtures/real_world_manifest.json.
"""

import json
from pathlib import Path
import cv2
import fitz
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent / "real_world_eval"
MANIFEST_PATH = Path(__file__).resolve().parent / "real_world_manifest.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _get_font_path() -> str:
    for c in _FONT_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


def _setup_page(doc: fitz.Document, width: int = 595, height: int = 842) -> tuple[fitz.Page, str]:
    page = doc.new_page(width=width, height=height)
    font_path = _get_font_path()
    alias = "vnfont"
    if font_path:
        try:
            page.insert_font(fontname=alias, fontfile=font_path)
            return page, alias
        except Exception:
            pass
    return page, "helv"


def _draw(
    page: fitz.Page,
    pt: tuple[float, float],
    text: str,
    font: str,
    size: float = 10,
    bold: bool = False,
):
    page.insert_text(pt, text, fontsize=size, fontname=font)


# ----------------------------------------------------------------------
# 1. PUB-01-EVN: Hóa đơn tiền điện EVN Hà Nội (Digital PDF)
# ----------------------------------------------------------------------
def generate_pub_01_evn():
    doc = fitz.open()
    page, f = _setup_page(doc)

    _draw(page, (180, 50), "HOA DON GIA TRI GIA TANG (TIEN DIEN)", f, size=15)
    _draw(page, (220, 70), "(Ban the hien cua hoa don dien tu)", f, size=9)

    _draw(page, (50, 105), "Ky hieu: 1C26TEE", f, size=10)
    _draw(page, (380, 105), "So hoa don: 0045231", f, size=10)
    _draw(page, (50, 125), "Ngay lap: 2026-03-01", f, size=10)
    _draw(page, (380, 125), "Loai tien: VND", f, size=10)

    _draw(page, (50, 155), "Don vi ban: Tong cong ty Dien luc TP Ha Noi", f, size=10)
    _draw(page, (50, 175), "Ma so thue: 0100100079", f, size=10)
    _draw(page, (50, 195), "Dia chi: So 69 Dinh Tien Hoang, Quan Hoan Kiem, Ha Noi", f, size=9)

    _draw(page, (50, 225), "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong", f, size=10)
    _draw(page, (50, 245), "Ma so thue: 0109998888", f, size=10)
    _draw(page, (50, 265), "Dia chi: So 12 Dao Duy Anh, Quan Dong Da, Ha Noi", f, size=9)

    y = 295
    page.draw_rect(fitz.Rect(50, y, 545, y + 24), fill=(0.9, 0.9, 0.9), color=(0.4, 0.4, 0.4))
    _draw(page, (55, y + 16), "STT", f, size=9)
    _draw(page, (90, y + 16), "Bo phan / Bac tieu thu", f, size=9)
    _draw(page, (270, y + 16), "Dien nang (kWh)", f, size=9)
    _draw(page, (360, y + 16), "Don gia (dong)", f, size=9)
    _draw(page, (460, y + 16), "Thanh tien (dong)", f, size=9)

    items = [
        ("1", "Dien nang kinh doanh Bac 1 [ELEC-TIER-1]", "100.0000", "1806.0000", "180600.0000"),
        ("2", "Dien nang kinh doanh Bac 2 [ELEC-TIER-2]", "150.0000", "2167.0000", "325050.0000"),
        ("3", "Dien nang kinh doanh Bac 3 [ELEC-TIER-3]", "200.0000", "2729.0000", "545800.0000"),
    ]
    curr_y = y + 24
    for stt, name, qty, price, amt in items:
        page.draw_rect(fitz.Rect(50, curr_y, 545, curr_y + 24), color=(0.7, 0.7, 0.7))
        _draw(page, (55, curr_y + 16), stt, f, size=9)
        _draw(page, (90, curr_y + 16), name, f, size=9)
        _draw(page, (270, curr_y + 16), qty, f, size=9)
        _draw(page, (360, curr_y + 16), price, f, size=9)
        _draw(page, (460, curr_y + 16), amt, f, size=9)
        curr_y += 24

    curr_y += 25
    _draw(page, (330, curr_y), "Cong tien dien (Subtotal): 1051450.0000", f, size=10)
    _draw(page, (330, curr_y + 20), "Tien thue GTGT (8%): 84116.0000", f, size=10)
    _draw(page, (330, curr_y + 40), "Tong cong tien thanh toan: 1135566.0000", f, size=10)

    out_file = OUTPUT_DIR / "pub_01_evn.pdf"
    doc.subset_fonts()
    doc.save(str(out_file), deflate=True, garbage=4)
    doc.close()


# ----------------------------------------------------------------------
# 2. PUB-02-VNPT: Hóa đơn viễn thông VNPT (Digital PDF)
# ----------------------------------------------------------------------
def generate_pub_02_vnpt():
    doc = fitz.open()
    page, f = _setup_page(doc)

    _draw(page, (160, 50), "HOA DON GIA TRI GIA TANG DICH VU VIEN THONG", f, size=14)
    _draw(page, (210, 70), "TAP DOAN BUU CHINH VIEN THONG VIET NAM", f, size=10)

    _draw(page, (50, 110), "Ky hieu: 1C26TVV", f, size=10)
    _draw(page, (380, 110), "So hoa don: 0089201", f, size=10)
    _draw(page, (50, 130), "Ngay lap: 2026-03-05", f, size=10)
    _draw(page, (380, 130), "Tien te: VND", f, size=10)

    _draw(page, (50, 160), "Don vi ban: Tap doan Buu chinh Vien thong Viet Nam", f, size=10)
    _draw(page, (50, 180), "Ma so thue: 0100684378", f, size=10)

    _draw(page, (50, 215), "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong", f, size=10)
    _draw(page, (50, 235), "Ma so thue: 0109998888", f, size=10)

    y = 270
    page.draw_rect(fitz.Rect(50, y, 545, y + 25), fill=(0.93, 0.93, 0.93), color=(0.5, 0.5, 0.5))
    _draw(page, (55, y + 17), "STT", f, size=9)
    _draw(page, (85, y + 17), "Ten dich vu viễn thông / Ma goi", f, size=9)
    _draw(page, (300, y + 17), "So luong", f, size=9)
    _draw(page, (370, y + 17), "Don gia", f, size=9)
    _draw(page, (460, y + 17), "Thanh tien", f, size=9)

    items = [
        (
            "1",
            "Cuoc Internet Cap quang FiberVNN 500Mbps [FIBER-500M]",
            "1.0000",
            "800000.0000",
            "800000.0000",
        ),
        (
            "2",
            "Cuoc dia chi IP tinh co dinh IPv4 [IP-STATIC-01]",
            "1.0000",
            "500000.0000",
            "500000.0000",
        ),
    ]
    curr_y = y + 25
    for stt, name, qty, price, amt in items:
        page.draw_rect(fitz.Rect(50, curr_y, 545, curr_y + 25), color=(0.75, 0.75, 0.75))
        _draw(page, (55, curr_y + 17), stt, f, size=9)
        _draw(page, (85, curr_y + 17), name, f, size=9)
        _draw(page, (300, curr_y + 17), qty, f, size=9)
        _draw(page, (370, curr_y + 17), price, f, size=9)
        _draw(page, (460, curr_y + 17), amt, f, size=9)
        curr_y += 25

    curr_y += 25
    _draw(page, (330, curr_y), "Cong tien dich vu: 1300000.0000", f, size=10)
    _draw(page, (330, curr_y + 20), "Tien thue GTGT (10%): 130000.0000", f, size=10)
    _draw(page, (330, curr_y + 40), "Tong cong tien thanh toan: 1430000.0000", f, size=10)

    out_file = OUTPUT_DIR / "pub_02_vnpt.pdf"
    doc.subset_fonts()
    doc.save(str(out_file), deflate=True, garbage=4)
    doc.close()


# ----------------------------------------------------------------------
# 3. PUB-03-PETROLIMEX: Hóa đơn xăng dầu Petrolimex (Scanned PDF)
# ----------------------------------------------------------------------
def generate_pub_03_petrolimex():
    doc = fitz.open()
    page, f = _setup_page(doc)

    _draw(page, (165, 50), "HOA DON GIA TRI GIA TANG XANG DAU", f, size=15)
    _draw(page, (190, 70), "TAP DOAN XANG DAU VIET NAM - PETROLIMEX", f, size=10)

    _draw(page, (50, 110), "Ky hieu: 1C26TPP", f, size=10)
    _draw(page, (380, 110), "So hoa don: 0077312", f, size=10)
    _draw(page, (50, 130), "Ngay lap: 2026-03-08", f, size=10)

    _draw(page, (50, 160), "Don vi ban: Tap doan Xang dau Viet Nam", f, size=10)
    _draw(page, (50, 180), "Ma so thue: 0100107624", f, size=10)

    _draw(page, (50, 215), "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong", f, size=10)
    _draw(page, (50, 235), "Ma so thue: 0109998888", f, size=10)

    y = 270
    page.draw_rect(fitz.Rect(50, y, 545, y + 25), fill=(0.92, 0.92, 0.92), color=(0.4, 0.4, 0.4))
    _draw(page, (55, y + 17), "STT", f, size=9)
    _draw(page, (90, y + 17), "Ten mat hang xang dau", f, size=9)
    _draw(page, (290, y + 17), "So luong (lit)", f, size=9)
    _draw(page, (370, y + 17), "Don gia (VND)", f, size=9)
    _draw(page, (460, y + 17), "Thanh tien", f, size=9)

    page.draw_rect(fitz.Rect(50, y + 25, 545, y + 50), color=(0.7, 0.7, 0.7))
    _draw(page, (55, y + 42), "1", f, size=9)
    _draw(page, (90, y + 42), "Xang khong chi RON 95-V [RON95-V]", f, size=9)
    _draw(page, (290, y + 42), "50.0000", f, size=9)
    _draw(page, (370, y + 42), "23500.0000", f, size=9)
    _draw(page, (460, y + 42), "1175000.0000", f, size=9)

    curr_y = y + 75
    _draw(page, (330, curr_y), "Cong tien hang: 1175000.0000", f, size=10)
    _draw(page, (330, curr_y + 20), "Tien thue GTGT (10%): 117500.0000", f, size=10)
    _draw(page, (330, curr_y + 40), "Tong cong tien thanh toan: 1292500.0000", f, size=10)

    # Render page to raster image to make it an authentic scanned PDF
    pix = page.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    doc.close()

    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=595, height=842)
    scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)

    out_file = OUTPUT_DIR / "pub_03_petrolimex.pdf"
    scan_doc.subset_fonts()
    scan_doc.save(str(out_file), deflate=True, garbage=4)
    scan_doc.close()


# ----------------------------------------------------------------------
# 4. Helper to draw clean invoice on blank white canvas
# ----------------------------------------------------------------------
def _render_base_invoice_cv2(
    title: str,
    series: str,
    no: str,
    date_s: str,
    sup_name: str,
    sup_tax: str,
    buy_name: str,
    buy_tax: str,
    lines: list[tuple[str, str, str, str, str]],
    subtotal: str,
    tax: str,
    total: str,
) -> np.ndarray:
    img = np.full((1200, 900, 3), 255, dtype=np.uint8)

    cv2.putText(img, title, (200, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(
        img,
        f"Ky hieu: {series}  So: {no}  Ngay: {date_s}",
        (80, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        1,
    )

    cv2.putText(
        img, f"Don vi ban: {sup_name}", (80, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1
    )
    cv2.putText(
        img, f"Ma so thue: {sup_tax}", (80, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1
    )

    cv2.putText(
        img, f"Don vi mua: {buy_name}", (80, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1
    )
    cv2.putText(
        img, f"Ma so thue: {buy_tax}", (80, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1
    )

    y = 350
    cv2.rectangle(img, (70, y), (830, y + 40), (220, 220, 220), -1)
    cv2.rectangle(img, (70, y), (830, y + 40), (0, 0, 0), 1)
    cv2.putText(img, "STT", (80, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(
        img, "Ten hang hoa / SKU", (140, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
    )
    cv2.putText(img, "So luong", (460, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Don gia", (560, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Thanh tien", (690, y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    curr_y = y + 40
    for stt, name, qty, price, amt in lines:
        cv2.rectangle(img, (70, curr_y), (830, curr_y + 45), (0, 0, 0), 1)
        cv2.putText(img, stt, (85, curr_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(img, name, (140, curr_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(img, qty, (470, curr_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(img, price, (560, curr_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(img, amt, (690, curr_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        curr_y += 45

    curr_y += 40
    cv2.putText(
        img,
        f"Cong tien hang: {subtotal}",
        (500, curr_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img,
        f"Tien thue GTGT: {tax}",
        (500, curr_y + 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img,
        f"Tong cong thanh toan: {total} VND",
        (440, curr_y + 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        2,
    )
    return img


# ----------------------------------------------------------------------
# 5. AUG-01-PERSPECTIVE: Ảnh chụp điện thoại góc nghiêng (Perspective distortion)
# ----------------------------------------------------------------------
def generate_aug_01_perspective():
    base_inv = _render_base_invoice_cv2(
        title="HOA DON BAN HANG (MOBILE PHOTO)",
        series="1C26TAA",
        no="0001055",
        date_s="2026-03-02",
        sup_name="Cong ty TNHH Thiet bi Tin hoc A Chau",
        sup_tax="0102223333",
        buy_name="Cong ty TNHH Giai phap Phan mem Tien Phong",
        buy_tax="0109998888",
        lines=[
            (
                "1",
                "Man hinh may tinh Dell 24 inch [DELL-24P]",
                "2.0000",
                "3500000.0000",
                "7000000.0000",
            ),
            ("2", "Ban phim co khong day [KB-MECH-01]", "3.0000", "1200000.0000", "3600000.0000"),
        ],
        subtotal="10600000.0000",
        tax="1060000.0000",
        total="11660000.0000",
    )
    # Create textured background (table surface)
    bg = np.full((1500, 1200, 3), (85, 95, 105), dtype=np.uint8)
    noise = np.random.randint(-15, 15, bg.shape, dtype=np.int16)
    bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    h, w = base_inv.shape[:2]
    src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    # Tilted 3D perspective trapezoid on table
    dst_pts = np.float32(
        [
            [220, 120],  # top-left
            [980, 160],  # top-right
            [1060, 1380],  # bottom-right
            [140, 1340],  # bottom-left
        ]
    )
    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(base_inv, matrix, (1200, 1500), borderMode=cv2.BORDER_TRANSPARENT)

    # Composite onto background
    mask = cv2.warpPerspective(np.full((h, w), 255, dtype=np.uint8), matrix, (1200, 1500))
    inv_mask = cv2.bitwise_not(mask)
    bg_masked = cv2.bitwise_and(bg, bg, mask=inv_mask)
    final_img = cv2.add(bg_masked, warped)

    out_file = OUTPUT_DIR / "aug_01_perspective.png"
    cv2.imwrite(str(out_file), final_img)


# ----------------------------------------------------------------------
# 6. AUG-02-SHADOW: Ảnh chụp điện thoại có bóng đổ che một phần (Shadow)
# ----------------------------------------------------------------------
def generate_aug_02_shadow():
    base_inv = _render_base_invoice_cv2(
        title="HOA DON DICH VU VAN TAI",
        series="1C26TLG",
        no="0002199",
        date_s="2026-03-04",
        sup_name="Cong ty CP Dich vu Hau can LogiTrans",
        sup_tax="0301112233",
        buy_name="Cong ty TNHH Giai phap Phan mem Tien Phong",
        buy_tax="0109998888",
        lines=[
            (
                "1",
                "Cuoc van chuyen hang hoa lien tinh [LOGI-INTER-01]",
                "1.0000",
                "4200000.0000",
                "4200000.0000",
            ),
        ],
        subtotal="4200000.0000",
        tax="420000.0000",
        total="4620000.0000",
    )
    h, w = base_inv.shape[:2]
    # Create shadow gradient mask across bottom-right
    y_coords, x_coords = np.ogrid[:h, :w]
    # Shadow centered around (w, h)
    dist = np.sqrt((x_coords - (w * 0.8)) ** 2 + (y_coords - (h * 0.8)) ** 2)
    shadow_factor = np.clip(1.0 - 0.55 * np.exp(-(dist**2) / (2 * (350**2))), 0.42, 1.0)
    shadowed = (base_inv.astype(np.float32) * shadow_factor[:, :, np.newaxis]).astype(np.uint8)

    out_file = OUTPUT_DIR / "aug_02_shadow.jpg"
    cv2.imwrite(str(out_file), shadowed, [cv2.IMWRITE_JPEG_QUALITY, 85])


# ----------------------------------------------------------------------
# 7. AUG-03-WRINKLED: Ảnh hóa đơn nhà hàng bị nhăn/gấp nếp
# ----------------------------------------------------------------------
def generate_aug_03_wrinkled():
    base_inv = _render_base_invoice_cv2(
        title="HOA DON AN UONG TIEP KHACH",
        series="1C26TRH",
        no="0005511",
        date_s="2026-03-06",
        sup_name="Nha hang Am thuc Pho Co",
        sup_tax="0103334455",
        buy_name="Cong ty TNHH Giai phap Phan mem Tien Phong",
        buy_tax="0109998888",
        lines=[
            (
                "1",
                "Set an tiep khach doanh nghiep [SET-VIP-04]",
                "5.0000",
                "550000.0000",
                "2750000.0000",
            ),
            (
                "2",
                "Nuoc uong khoang thien nhien [WATER-01]",
                "10.0000",
                "25000.0000",
                "250000.0000",
            ),
        ],
        subtotal="3000000.0000",
        tax="240000.0000",
        total="3240000.0000",
    )
    h, w = base_inv.shape[:2]
    # Apply crease mesh displacement
    mesh_x, mesh_y = np.meshgrid(np.arange(w), np.arange(h))
    disp_x = (np.sin(mesh_y / 35.0) * 4.0).astype(np.float32)
    disp_y = (np.cos(mesh_x / 40.0) * 3.0).astype(np.float32)
    map_x = np.clip(mesh_x + disp_x, 0, w - 1).astype(np.float32)
    map_y = np.clip(mesh_y + disp_y, 0, h - 1).astype(np.float32)
    wrinkled = cv2.remap(base_inv, map_x, map_y, cv2.INTER_LINEAR)

    # Add dark crease lines across folds
    cv2.line(wrinkled, (0, int(h * 0.33)), (w, int(h * 0.35)), (180, 180, 180), 2)
    cv2.line(wrinkled, (0, int(h * 0.67)), (w, int(h * 0.65)), (175, 175, 175), 2)

    out_file = OUTPUT_DIR / "aug_03_wrinkled.png"
    cv2.imwrite(str(out_file), wrinkled)


# ----------------------------------------------------------------------
# 8. AUG-04-COMPLEX-BG: Hóa đơn trên nền bàn làm việc có vật thể
# ----------------------------------------------------------------------
def generate_aug_04_complex_bg():
    base_inv = _render_base_invoice_cv2(
        title="HOA DON VAN PHONG PHAM",
        series="1C26TVP",
        no="0003322",
        date_s="2026-03-07",
        sup_name="Cong ty TNHH Van phong pham Hong Ha",
        sup_tax="0100100147",
        buy_name="Cong ty TNHH Giai phap Phan mem Tien Phong",
        buy_tax="0109998888",
        lines=[
            ("1", "But bi thien long xanh [PEN-TL-01]", "50.0000", "5000.0000", "250000.0000"),
            ("2", "Tap bia ho so co cong 7cm [FILE-7CM]", "10.0000", "45000.0000", "450000.0000"),
        ],
        subtotal="700000.0000",
        tax="56000.0000",
        total="756000.0000",
    )
    # Background canvas
    bg = np.full((1400, 1100, 3), (70, 75, 80), dtype=np.uint8)
    # Add random pen / ruler object shapes on background
    cv2.rectangle(bg, (50, 200), (80, 1100), (30, 30, 180), -1)  # ruler
    cv2.circle(bg, (1020, 300), 50, (40, 100, 160), -1)  # tape roll

    # Place invoice inside background
    bh, bw = base_inv.shape[:2]
    bg[100 : 100 + bh, 100 : 100 + bw] = base_inv

    out_file = OUTPUT_DIR / "aug_04_complex_bg.jpg"
    cv2.imwrite(str(out_file), bg, [cv2.IMWRITE_JPEG_QUALITY, 90])


# ----------------------------------------------------------------------
# 9. AUG-05-MULTI-LINE: Hóa đơn 8 dòng hàng (Scanned PDF)
# ----------------------------------------------------------------------
def generate_aug_05_multi_line():
    doc = fitz.open()
    page, f = _setup_page(doc)

    _draw(page, (160, 45), "HOA DON GIA TRI GIA TANG (LINH KIEN MAY TINH)", f, size=13)
    _draw(page, (50, 80), "Ky hieu: 1C26TPV", f, size=9)
    _draw(page, (380, 80), "So: 0009841", f, size=9)
    _draw(page, (50, 98), "Ngay: 2026-03-09", f, size=9)
    _draw(page, (50, 120), "Don vi ban: Cong ty Co phan Cong nghe Phong Vu", f, size=9)
    _draw(page, (50, 138), "Ma so thue: 0304998368", f, size=9)
    _draw(page, (50, 162), "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong", f, size=9)
    _draw(page, (50, 180), "Ma so thue: 0109998888", f, size=9)

    y = 205
    page.draw_rect(fitz.Rect(50, y, 545, y + 20), fill=(0.92, 0.92, 0.92), color=(0.4, 0.4, 0.4))
    _draw(page, (55, y + 14), "STT", f, size=8)
    _draw(page, (85, y + 14), "Ten linh kien, phu kien / SKU", f, size=8)
    _draw(page, (300, y + 14), "SL", f, size=8)
    _draw(page, (360, y + 14), "Don gia", f, size=8)
    _draw(page, (460, y + 14), "Thanh tien", f, size=8)

    lines = [
        (
            "1",
            "CPU Intel Core i7 14700K [CPU-I7-14700K]",
            "2.0000",
            "9500000.0000",
            "19000000.0000",
        ),
        (
            "2",
            "Mainboard Asus ROG Strix Z790 [MB-Z790-STRIX]",
            "2.0000",
            "8200000.0000",
            "16400000.0000",
        ),
        (
            "3",
            "RAM Corsair Vengeance 32GB DDR5 [RAM-32GB-D5]",
            "4.0000",
            "2800000.0000",
            "11200000.0000",
        ),
        (
            "4",
            "SSD Samsung 990 Pro 2TB NVMe [SSD-2TB-990P]",
            "3.0000",
            "4200000.0000",
            "12600000.0000",
        ),
        (
            "5",
            "VGA Gigabyte RTX 4070 Super [VGA-RTX4070S]",
            "1.0000",
            "17500000.0000",
            "17500000.0000",
        ),
        (
            "6",
            "Nguon Seasonic Focus 850W Gold [PSU-850W-GOLD]",
            "2.0000",
            "3100000.0000",
            "6200000.0000",
        ),
        (
            "7",
            "Vo case Fractal Design North [CASE-FRACTAL-N]",
            "2.0000",
            "3600000.0000",
            "7200000.0000",
        ),
        (
            "8",
            "Tan nhiet nuoc AIO DeepCool LT720 [COOL-LT720]",
            "2.0000",
            "2900000.0000",
            "5800000.0000",
        ),
    ]
    curr_y = y + 20
    for stt, name, qty, price, amt in lines:
        page.draw_rect(fitz.Rect(50, curr_y, 545, curr_y + 20), color=(0.75, 0.75, 0.75))
        _draw(page, (55, curr_y + 14), stt, f, size=8)
        _draw(page, (85, curr_y + 14), name, f, size=8)
        _draw(page, (300, curr_y + 14), qty, f, size=8)
        _draw(page, (360, curr_y + 14), price, f, size=8)
        _draw(page, (460, curr_y + 14), amt, f, size=8)
        curr_y += 20

    curr_y += 25
    _draw(page, (330, curr_y), "Cong tien hang: 95900000.0000", f, size=9)
    _draw(page, (330, curr_y + 18), "Tien thue GTGT (10%): 9590000.0000", f, size=9)
    _draw(page, (330, curr_y + 36), "Tong cong thanh toan: 105490000.0000", f, size=9)

    pix = page.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    doc.close()

    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=595, height=842)
    scan_page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)

    out_file = OUTPUT_DIR / "aug_05_multi_line.pdf"
    scan_doc.subset_fonts()
    scan_doc.save(str(out_file), deflate=True, garbage=4)
    scan_doc.close()


# ----------------------------------------------------------------------
# 10. AUG-06-MULTI-PAGE: Hóa đơn 2 trang kèm bảng kê (Digital PDF)
# ----------------------------------------------------------------------
def generate_aug_06_multi_page():
    doc = fitz.open()
    # Page 1: General invoice info & summary
    page1, f1 = _setup_page(doc)
    _draw(page1, (180, 50), "HOA DON GIA TRI GIA TANG (TRANG 1/2)", f1, size=14)
    _draw(page1, (50, 100), "Ky hieu: 1C26TFPT  So: 0008821  Ngay: 2026-03-10", f1, size=10)
    _draw(page1, (50, 130), "Don vi ban: Cong ty Co phan Vien thong FPT", f1, size=10)
    _draw(page1, (50, 150), "Ma so thue: 0101778163", f1, size=10)
    _draw(page1, (50, 185), "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong", f1, size=10)
    _draw(page1, (50, 205), "Ma so thue: 0109998888", f1, size=10)
    _draw(page1, (50, 240), "Chi tiet dich vu xem bang ke so BK-2026-03 tai Trang 2.", f1, size=10)

    _draw(page1, (320, 300), "Cong tien hang: 25000000.0000", f1, size=10)
    _draw(page1, (320, 325), "Tien thue GTGT (10%): 2500000.0000", f1, size=10)
    _draw(page1, (320, 350), "Tong thanh toan: 27500000.0000 VND", f1, size=10)

    # Page 2: Detailed items table
    page2, f2 = _setup_page(doc)
    _draw(page2, (180, 50), "BANG KE CHI TIET DICH VU (TRANG 2/2)", f2, size=14)
    _draw(page2, (50, 80), "Kem theo hoa don so: 0008821  Ky hieu: 1C26TFPT", f2, size=10)

    y = 120
    page2.draw_rect(fitz.Rect(50, y, 545, y + 25), fill=(0.92, 0.92, 0.92), color=(0.4, 0.4, 0.4))
    _draw(page2, (55, y + 17), "STT", f2, size=9)
    _draw(page2, (90, y + 17), "Noi dung dich vu dien toan dam may / SKU", f2, size=9)
    _draw(page2, (320, y + 17), "So luong", f2, size=9)
    _draw(page2, (380, y + 17), "Don gia", f2, size=9)
    _draw(page2, (470, y + 17), "Thanh tien", f2, size=9)

    items = [
        (
            "1",
            "Dich vu Cloud Server vCPU 8 Ram 16GB [FPT-CLOUD-S8]",
            "1.0000",
            "15000000.0000",
            "15000000.0000",
        ),
        (
            "2",
            "Dich vu Object Storage 5TB S3 compatible [FPT-S3-5TB]",
            "1.0000",
            "10000000.0000",
            "10000000.0000",
        ),
    ]
    curr_y = y + 25
    for stt, name, qty, price, amt in items:
        page2.draw_rect(fitz.Rect(50, curr_y, 545, curr_y + 25), color=(0.75, 0.75, 0.75))
        _draw(page2, (55, curr_y + 17), stt, f2, size=9)
        _draw(page2, (90, curr_y + 17), name, f2, size=9)
        _draw(page2, (320, curr_y + 17), qty, f2, size=9)
        _draw(page2, (380, curr_y + 17), price, f2, size=9)
        _draw(page2, (470, curr_y + 17), amt, f2, size=9)
        curr_y += 25

    out_file = OUTPUT_DIR / "aug_06_multi_page.pdf"
    doc.subset_fonts()
    doc.save(str(out_file), deflate=True, garbage=4)
    doc.close()


# ----------------------------------------------------------------------
# 11. AUG-07-SKEW-LOWLIGHT: Hóa đơn xoay 7 độ và thiếu sáng
# ----------------------------------------------------------------------
def generate_aug_07_skew_lowlight():
    base_inv = _render_base_invoice_cv2(
        title="HOA DON TIEP KHACH VA DU LICH",
        series="1C26TTH",
        no="0004456",
        date_s="2026-03-11",
        sup_name="Cong ty TNHH Thuong mai Dich vu Tan Hung",
        sup_tax="0309995544",
        buy_name="Cong ty TNHH Giai phap Phan mem Tien Phong",
        buy_tax="0109998888",
        lines=[
            (
                "1",
                "Dich vu phong nghi hoi nghi khach hang [ROOM-VIP-01]",
                "2.0000",
                "2200000.0000",
                "4400000.0000",
            ),
        ],
        subtotal="4400000.0000",
        tax="352000.0000",
        total="4752000.0000",
    )
    # Low brightness: scale down pixel intensity
    lowlight = (base_inv.astype(np.float32) * 0.58).astype(np.uint8)

    # Rotate 7.0 degrees
    h, w = lowlight.shape[:2]
    center = (w // 2, h // 2)
    rot_mat = cv2.getRotationMatrix2D(center, 7.0, 1.0)
    skewed = cv2.warpAffine(lowlight, rot_mat, (w, h), borderValue=(50, 50, 50))

    out_file = OUTPUT_DIR / "aug_07_skew_lowlight.png"
    cv2.imwrite(str(out_file), skewed)


# ----------------------------------------------------------------------
# 12. Main: generate all fixtures and output JSON manifest
# ----------------------------------------------------------------------
def main():
    print("Generating real-world evaluation fixtures in:", OUTPUT_DIR)
    generate_pub_01_evn()
    generate_pub_02_vnpt()
    generate_pub_03_petrolimex()
    generate_aug_01_perspective()
    generate_aug_02_shadow()
    generate_aug_03_wrinkled()
    generate_aug_04_complex_bg()
    generate_aug_05_multi_line()
    generate_aug_06_multi_page()
    generate_aug_07_skew_lowlight()
    print("Documents generated successfully.")

    manifest = [
        # --- PUBLIC SAMPLES ---
        {
            "case_id": "PUB-01-EVN",
            "dataset_category": "public_sample",
            "difficulty": "easy",
            "format": "pdf",
            "filename": "pub_01_evn.pdf",
            "description": "Hóa đơn tiền điện EVN Hà Nội dạng Digital PDF với bảng điện năng bậc thang",
            "distortions": [],
            "vendor_domain": "energy",
            "header": {
                "supplier_tax_id": "0100100079",
                "supplier_name": "Tong cong ty Dien luc TP Ha Noi",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0045231",
                "invoice_series": "1C26TEE",
                "issue_date": "2026-03-01",
                "currency": "VND",
                "subtotal": "1051450.0000",
                "tax_total": "84116.0000",
                "amount_payable": "1135566.0000",
            },
            "lines": [
                {
                    "sku": "ELEC-TIER-1",
                    "description": "Dien nang kinh doanh Bac 1 [ELEC-TIER-1]",
                    "qty": "100.0000",
                    "unit_price": "1806.0000",
                    "tax_rate": "8.00",
                    "line_amount": "180600.0000",
                },
                {
                    "sku": "ELEC-TIER-2",
                    "description": "Dien nang kinh doanh Bac 2 [ELEC-TIER-2]",
                    "qty": "150.0000",
                    "unit_price": "2167.0000",
                    "tax_rate": "8.00",
                    "line_amount": "325050.0000",
                },
                {
                    "sku": "ELEC-TIER-3",
                    "description": "Dien nang kinh doanh Bac 3 [ELEC-TIER-3]",
                    "qty": "200.0000",
                    "unit_price": "2729.0000",
                    "tax_rate": "8.00",
                    "line_amount": "545800.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON GIA TRI GIA TANG (TIEN DIEN)\n"
                "Ky hieu: 1C26TEE  So hoa don: 0045231  Ngay lap: 2026-03-01\n"
                "Don vi ban: Tong cong ty Dien luc TP Ha Noi  Ma so thue: 0100100079\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Dien nang kinh doanh Bac 1 [ELEC-TIER-1]  100.0000  1806.0000  180600.0000\n"
                "Dien nang kinh doanh Bac 2 [ELEC-TIER-2]  150.0000  2167.0000  325050.0000\n"
                "Dien nang kinh doanh Bac 3 [ELEC-TIER-3]  200.0000  2729.0000  545800.0000\n"
                "Cong tien dien: 1051450.0000  Tien thue GTGT: 84116.0000  Tong cong tien thanh toan: 1135566.0000"
            ),
        },
        {
            "case_id": "PUB-02-VNPT",
            "dataset_category": "public_sample",
            "difficulty": "easy",
            "format": "pdf",
            "filename": "pub_02_vnpt.pdf",
            "description": "Hóa đơn cước viễn thông VNPT dạng Digital PDF với bảng dịch vụ cáp quang và IP tĩnh",
            "distortions": [],
            "vendor_domain": "telecom",
            "header": {
                "supplier_tax_id": "0100684378",
                "supplier_name": "Tap doan Buu chinh Vien thong Viet Nam",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0089201",
                "invoice_series": "1C26TVV",
                "issue_date": "2026-03-05",
                "currency": "VND",
                "subtotal": "1300000.0000",
                "tax_total": "130000.0000",
                "amount_payable": "1430000.0000",
            },
            "lines": [
                {
                    "sku": "FIBER-500M",
                    "description": "Cuoc Internet Cap quang FiberVNN 500Mbps [FIBER-500M]",
                    "qty": "1.0000",
                    "unit_price": "800000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "800000.0000",
                },
                {
                    "sku": "IP-STATIC-01",
                    "description": "Cuoc dia chi IP tinh co dinh IPv4 [IP-STATIC-01]",
                    "qty": "1.0000",
                    "unit_price": "500000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "500000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON GIA TRI GIA TANG DICH VU VIEN THONG\n"
                "Ky hieu: 1C26TVV  So hoa don: 0089201  Ngay lap: 2026-03-05\n"
                "Don vi ban: Tap doan Buu chinh Vien thong Viet Nam  Ma so thue: 0100684378\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Cuoc Internet Cap quang FiberVNN 500Mbps [FIBER-500M]  1.0000  800000.0000  800000.0000\n"
                "Cuoc dia chi IP tinh co dinh IPv4 [IP-STATIC-01]  1.0000  500000.0000  500000.0000\n"
                "Cong tien dich vu: 1300000.0000  Tien thue GTGT: 130000.0000  Tong cong tien thanh toan: 1430000.0000"
            ),
        },
        {
            "case_id": "PUB-03-PETROLIMEX",
            "dataset_category": "public_sample",
            "difficulty": "medium",
            "format": "pdf",
            "filename": "pub_03_petrolimex.pdf",
            "description": "Hóa đơn xăng dầu Petrolimex dạng Scanned PDF (ảnh quét raster)",
            "distortions": ["scanned_raster"],
            "vendor_domain": "fuel",
            "header": {
                "supplier_tax_id": "0100107624",
                "supplier_name": "Tap doan Xang dau Viet Nam",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0077312",
                "invoice_series": "1C26TPP",
                "issue_date": "2026-03-08",
                "currency": "VND",
                "subtotal": "1175000.0000",
                "tax_total": "117500.0000",
                "amount_payable": "1292500.0000",
            },
            "lines": [
                {
                    "sku": "RON95-V",
                    "description": "Xang khong chi RON 95-V [RON95-V]",
                    "qty": "50.0000",
                    "unit_price": "23500.0000",
                    "tax_rate": "10.00",
                    "line_amount": "1175000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON GIA TRI GIA TANG XANG DAU\n"
                "Ky hieu: 1C26TPP  So hoa don: 0077312  Ngay lap: 2026-03-08\n"
                "Don vi ban: Tap doan Xang dau Viet Nam  Ma so thue: 0100107624\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Xang khong chi RON 95-V [RON95-V]  50.0000  23500.0000  1175000.0000\n"
                "Cong tien hang: 1175000.0000  Tien thue GTGT: 117500.0000  Tong cong tien thanh toan: 1292500.0000"
            ),
        },
        # --- AUGMENTED MOBILE IMAGES ---
        {
            "case_id": "AUG-01-PERSPECTIVE",
            "dataset_category": "augmented_image",
            "difficulty": "hard",
            "format": "png",
            "filename": "aug_01_perspective.png",
            "description": "Ảnh chụp điện thoại góc nghiêng 15 độ với biến dạng phối cảnh 3D trên nền bàn làm việc",
            "distortions": ["perspective_distortion", "background_texture"],
            "vendor_domain": "hardware",
            "header": {
                "supplier_tax_id": "0102223333",
                "supplier_name": "Cong ty TNHH Thiet bi Tin hoc A Chau",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0001055",
                "invoice_series": "1C26TAA",
                "issue_date": "2026-03-02",
                "currency": "VND",
                "subtotal": "10600000.0000",
                "tax_total": "1060000.0000",
                "amount_payable": "11660000.0000",
            },
            "lines": [
                {
                    "sku": "DELL-24P",
                    "description": "Man hinh may tinh Dell 24 inch [DELL-24P]",
                    "qty": "2.0000",
                    "unit_price": "3500000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "7000000.0000",
                },
                {
                    "sku": "KB-MECH-01",
                    "description": "Ban phim co khong day [KB-MECH-01]",
                    "qty": "3.0000",
                    "unit_price": "1200000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "3600000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON BAN HANG (MOBILE PHOTO)\n"
                "Ky hieu: 1C26TAA  So: 0001055  Ngay: 2026-03-02\n"
                "Don vi ban: Cong ty TNHH Thiet bi Tin hoc A Chau  Ma so thue: 0102223333\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Man hinh may tinh Dell 24 inch [DELL-24P]  2.0000  3500000.0000  7000000.0000\n"
                "Ban phim co khong day [KB-MECH-01]  3.0000  1200000.0000  3600000.0000\n"
                "Cong tien hang: 10600000.0000  Tien thue GTGT: 1060000.0000  Tong cong thanh toan: 11660000.0000"
            ),
        },
        {
            "case_id": "AUG-02-SHADOW",
            "dataset_category": "augmented_image",
            "difficulty": "hard",
            "format": "jpeg",
            "filename": "aug_02_shadow.jpg",
            "description": "Ảnh chụp điện thoại có bóng đổ che khuất và ánh sáng không đều (shadow occlusion)",
            "distortions": ["shadow_occlusion", "uneven_illumination"],
            "vendor_domain": "logistics",
            "header": {
                "supplier_tax_id": "0301112233",
                "supplier_name": "Cong ty CP Dich vu Hau can LogiTrans",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0002199",
                "invoice_series": "1C26TLG",
                "issue_date": "2026-03-04",
                "currency": "VND",
                "subtotal": "4200000.0000",
                "tax_total": "420000.0000",
                "amount_payable": "4620000.0000",
            },
            "lines": [
                {
                    "sku": "LOGI-INTER-01",
                    "description": "Cuoc van chuyen hang hoa lien tinh [LOGI-INTER-01]",
                    "qty": "1.0000",
                    "unit_price": "4200000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "4200000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON DICH VU VAN TAI\n"
                "Ky hieu: 1C26TLG  So: 0002199  Ngay: 2026-03-04\n"
                "Don vi ban: Cong ty CP Dich vu Hau can LogiTrans  Ma so thue: 0301112233\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Cuoc van chuyen hang hoa lien tinh [LOGI-INTER-01]  1.0000  4200000.0000  4200000.0000\n"
                "Cong tien hang: 4200000.0000  Tien thue GTGT: 420000.0000  Tong cong thanh toan: 4620000.0000"
            ),
        },
        {
            "case_id": "AUG-03-WRINKLED",
            "dataset_category": "augmented_image",
            "difficulty": "hard",
            "format": "png",
            "filename": "aug_03_wrinkled.png",
            "description": "Ảnh hóa đơn nhà hàng bị nhăn nheo, gập nếp ngang (folds and wrinkles)",
            "distortions": ["wrinkles", "creases", "line_distortion"],
            "vendor_domain": "restaurant",
            "header": {
                "supplier_tax_id": "0103334455",
                "supplier_name": "Nha hang Am thuc Pho Co",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0005511",
                "invoice_series": "1C26TRH",
                "issue_date": "2026-03-06",
                "currency": "VND",
                "subtotal": "3000000.0000",
                "tax_total": "240000.0000",
                "amount_payable": "3240000.0000",
            },
            "lines": [
                {
                    "sku": "SET-VIP-04",
                    "description": "Set an tiep khach doanh nghiep [SET-VIP-04]",
                    "qty": "5.0000",
                    "unit_price": "550000.0000",
                    "tax_rate": "8.00",
                    "line_amount": "2750000.0000",
                },
                {
                    "sku": "WATER-01",
                    "description": "Nuoc uong khoang thien nhien [WATER-01]",
                    "qty": "10.0000",
                    "unit_price": "25000.0000",
                    "tax_rate": "8.00",
                    "line_amount": "250000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON AN UONG TIEP KHACH\n"
                "Ky hieu: 1C26TRH  So: 0005511  Ngay: 2026-03-06\n"
                "Don vi ban: Nha hang Am thuc Pho Co  Ma so thue: 0103334455\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Set an tiep khach doanh nghiep [SET-VIP-04]  5.0000  550000.0000  2750000.0000\n"
                "Nuoc uong khoang thien nhien [WATER-01]  10.0000  25000.0000  250000.0000\n"
                "Cong tien hang: 3000000.0000  Tien thue GTGT: 240000.0000  Tong cong thanh toan: 3240000.0000"
            ),
        },
        {
            "case_id": "AUG-04-COMPLEX-BG",
            "dataset_category": "augmented_image",
            "difficulty": "medium",
            "format": "jpeg",
            "filename": "aug_04_complex_bg.jpg",
            "description": "Hóa đơn đặt trên bàn làm việc có vật thể xung quanh và viền nền phức tạp",
            "distortions": ["complex_background", "edge_noise"],
            "vendor_domain": "office_supplies",
            "header": {
                "supplier_tax_id": "0100100147",
                "supplier_name": "Cong ty TNHH Van phong pham Hong Ha",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0003322",
                "invoice_series": "1C26TVP",
                "issue_date": "2026-03-07",
                "currency": "VND",
                "subtotal": "700000.0000",
                "tax_total": "56000.0000",
                "amount_payable": "756000.0000",
            },
            "lines": [
                {
                    "sku": "PEN-TL-01",
                    "description": "But bi thien long xanh [PEN-TL-01]",
                    "qty": "50.0000",
                    "unit_price": "5000.0000",
                    "tax_rate": "8.00",
                    "line_amount": "250000.0000",
                },
                {
                    "sku": "FILE-7CM",
                    "description": "Tap bia ho so co cong 7cm [FILE-7CM]",
                    "qty": "10.0000",
                    "unit_price": "45000.0000",
                    "tax_rate": "8.00",
                    "line_amount": "450000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON VAN PHONG PHAM\n"
                "Ky hieu: 1C26TVP  So: 0003322  Ngay: 2026-03-07\n"
                "Don vi ban: Cong ty TNHH Van phong pham Hong Ha  Ma so thue: 0100100147\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "But bi thien long xanh [PEN-TL-01]  50.0000  5000.0000  250000.0000\n"
                "Tap bia ho so co cong 7cm [FILE-7CM]  10.0000  45000.0000  450000.0000\n"
                "Cong tien hang: 700000.0000  Tien thue GTGT: 56000.0000  Tong cong thanh toan: 756000.0000"
            ),
        },
        {
            "case_id": "AUG-05-MULTI-LINE",
            "dataset_category": "augmented_image",
            "difficulty": "medium",
            "format": "pdf",
            "filename": "aug_05_multi_line.pdf",
            "description": "Hóa đơn linh kiện máy tính 8 dòng hàng dạng scan ảnh",
            "distortions": ["multi_line_table", "scanned_raster"],
            "vendor_domain": "hardware",
            "header": {
                "supplier_tax_id": "0304998368",
                "supplier_name": "Cong ty Co phan Cong nghe Phong Vu",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0009841",
                "invoice_series": "1C26TPV",
                "issue_date": "2026-03-09",
                "currency": "VND",
                "subtotal": "95900000.0000",
                "tax_total": "9590000.0000",
                "amount_payable": "105490000.0000",
            },
            "lines": [
                {
                    "sku": "CPU-I7-14700K",
                    "description": "CPU Intel Core i7 14700K [CPU-I7-14700K]",
                    "qty": "2.0000",
                    "unit_price": "9500000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "19000000.0000",
                },
                {
                    "sku": "MB-Z790-STRIX",
                    "description": "Mainboard Asus ROG Strix Z790 [MB-Z790-STRIX]",
                    "qty": "2.0000",
                    "unit_price": "8200000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "16400000.0000",
                },
                {
                    "sku": "RAM-32GB-D5",
                    "description": "RAM Corsair Vengeance 32GB DDR5 [RAM-32GB-D5]",
                    "qty": "4.0000",
                    "unit_price": "2800000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "11200000.0000",
                },
                {
                    "sku": "SSD-2TB-990P",
                    "description": "SSD Samsung 990 Pro 2TB NVMe [SSD-2TB-990P]",
                    "qty": "3.0000",
                    "unit_price": "4200000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "12600000.0000",
                },
                {
                    "sku": "VGA-RTX4070S",
                    "description": "VGA Gigabyte RTX 4070 Super [VGA-RTX4070S]",
                    "qty": "1.0000",
                    "unit_price": "17500000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "17500000.0000",
                },
                {
                    "sku": "PSU-850W-GOLD",
                    "description": "Nguon Seasonic Focus 850W Gold [PSU-850W-GOLD]",
                    "qty": "2.0000",
                    "unit_price": "3100000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "6200000.0000",
                },
                {
                    "sku": "CASE-FRACTAL-N",
                    "description": "Vo case Fractal Design North [CASE-FRACTAL-N]",
                    "qty": "2.0000",
                    "unit_price": "3600000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "7200000.0000",
                },
                {
                    "sku": "COOL-LT720",
                    "description": "Tan nhiet nuoc AIO DeepCool LT720 [COOL-LT720]",
                    "qty": "2.0000",
                    "unit_price": "2900000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "5800000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON GIA TRI GIA TANG (LINH KIEN MAY TINH)\n"
                "Ky hieu: 1C26TPV  So: 0009841  Ngay: 2026-03-09\n"
                "Don vi ban: Cong ty Co phan Cong nghe Phong Vu  Ma so thue: 0304998368\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Cong tien hang: 95900000.0000  Tien thue GTGT: 9590000.0000  Tong cong thanh toan: 105490000.0000"
            ),
        },
        {
            "case_id": "AUG-06-MULTI-PAGE",
            "dataset_category": "augmented_image",
            "difficulty": "medium",
            "format": "pdf",
            "filename": "aug_06_multi_page.pdf",
            "description": "Hóa đơn dịch vụ điện toán đám mây FPT Telecom 2 trang kèm bảng kê chi tiết",
            "distortions": ["multi_page"],
            "vendor_domain": "cloud",
            "header": {
                "supplier_tax_id": "0101778163",
                "supplier_name": "Cong ty Co phan Vien thong FPT",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0008821",
                "invoice_series": "1C26TFPT",
                "issue_date": "2026-03-10",
                "currency": "VND",
                "subtotal": "25000000.0000",
                "tax_total": "2500000.0000",
                "amount_payable": "27500000.0000",
            },
            "lines": [
                {
                    "sku": "FPT-CLOUD-S8",
                    "description": "Dich vu Cloud Server vCPU 8 Ram 16GB [FPT-CLOUD-S8]",
                    "qty": "1.0000",
                    "unit_price": "15000000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "15000000.0000",
                },
                {
                    "sku": "FPT-S3-5TB",
                    "description": "Dich vu Object Storage 5TB S3 compatible [FPT-S3-5TB]",
                    "qty": "1.0000",
                    "unit_price": "10000000.0000",
                    "tax_rate": "10.00",
                    "line_amount": "10000000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON GIA TRI GIA TANG (TRANG 1/2)\n"
                "Ky hieu: 1C26TFPT  So: 0008821  Ngay: 2026-03-10\n"
                "Don vi ban: Cong ty Co phan Vien thong FPT  Ma so thue: 0101778163\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Dich vu Cloud Server vCPU 8 Ram 16GB [FPT-CLOUD-S8]  1.0000  15000000.0000  15000000.0000\n"
                "Dich vu Object Storage 5TB S3 compatible [FPT-S3-5TB]  1.0000  10000000.0000  10000000.0000\n"
                "Cong tien hang: 25000000.0000  Tien thue GTGT: 2500000.0000  Tong thanh toan: 27500000.0000"
            ),
        },
        {
            "case_id": "AUG-07-SKEW-LOWLIGHT",
            "dataset_category": "augmented_image",
            "difficulty": "hard",
            "format": "png",
            "filename": "aug_07_skew_lowlight.png",
            "description": "Hóa đơn dịch vụ nghỉ dưỡng bị xoay 7 độ và chụp trong điều kiện thiếu sáng (low contrast)",
            "distortions": ["skew_7deg", "low_light"],
            "vendor_domain": "hospitality",
            "header": {
                "supplier_tax_id": "0309995544",
                "supplier_name": "Cong ty TNHH Thuong mai Dich vu Tan Hung",
                "buyer_tax_id": "0109998888",
                "buyer_name": "Cong ty TNHH Giai phap Phan mem Tien Phong",
                "invoice_number": "0004456",
                "invoice_series": "1C26TTH",
                "issue_date": "2026-03-11",
                "currency": "VND",
                "subtotal": "4400000.0000",
                "tax_total": "352000.0000",
                "amount_payable": "4752000.0000",
            },
            "lines": [
                {
                    "sku": "ROOM-VIP-01",
                    "description": "Dich vu phong nghi hoi nghi khach hang [ROOM-VIP-01]",
                    "qty": "2.0000",
                    "unit_price": "2200000.0000",
                    "tax_rate": "8.00",
                    "line_amount": "4400000.0000",
                },
            ],
            "unreadable_fields": {},
            "reference_text": (
                "HOA DON TIEP KHACH VA DU LICH\n"
                "Ky hieu: 1C26TTH  So: 0004456  Ngay: 2026-03-11\n"
                "Don vi ban: Cong ty TNHH Thuong mai Dich vu Tan Hung  Ma so thue: 0309995544\n"
                "Don vi mua: Cong ty TNHH Giai phap Phan mem Tien Phong  Ma so thue: 0109998888\n"
                "Dich vu phong nghi hoi nghi khach hang [ROOM-VIP-01]  2.0000  2200000.0000  4400000.0000\n"
                "Cong tien hang: 4400000.0000  Tien thue GTGT: 352000.0000  Tong cong thanh toan: 4752000.0000"
            ),
        },
    ]

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Manifest written with {len(manifest)} cases to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
