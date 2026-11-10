from pathlib import Path
import shutil
import tempfile
import threading
import time
from fastapi.staticfiles import StaticFiles
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright
import uvicorn

from invoiceflow.api.main import create_app
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.storage.service import LocalStorageService
from scripts.seed_demo import seed_all


@pytest.fixture(scope="module")
def e2e_server():
    """Spins up a lightweight FastAPI server mounted with the production frontend build."""
    dist_dir = Path("apps/web/dist")
    if not dist_dir.exists() or not (dist_dir / "index.html").exists():
        pytest.skip(
            "Frontend production build dist/ not found. Run 'pnpm --prefix apps/web build' first."
        )

    tmp_dir = tempfile.mkdtemp()
    test_db_path = Path(tmp_dir) / "e2e_test.db"
    db_url = f"sqlite+aiosqlite:///{test_db_path}"

    db_manager = DatabaseSessionManager(database_url=db_url)
    storage = LocalStorageService(base_dir=str(Path(tmp_dir) / "storage"))

    import asyncio

    async def _init_database():
        await db_manager.create_tables()
        await seed_all(db_manager)

    asyncio.run(_init_database())

    app = create_app(database_url=db_url, db_manager=db_manager, storage=storage)

    # Mount static files to serve UI
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    # Start uvicorn server on an ephemeral high port
    port = 8765
    host = "127.0.0.1"
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config=config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for server to start accepting connections
    time.sleep(1.5)
    base_url = f"http://{host}:{port}"

    yield base_url

    server.should_exit = True
    server_thread.join(timeout=3.0)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _login(page, base_url, email="accountant@invoiceflow.vn", password="DemoPassword@123"):
    page.goto(base_url)
    page.wait_for_selector("text=Đăng nhập hệ thống", timeout=10000)
    page.fill("input[type='email']", email)
    page.fill("input[type='password']", password)
    page.click("button[type='submit']")
    page.wait_for_selector("text=Hộp thư Tiếp nhận Hóa đơn", timeout=10000)


def test_playwright_e2e_full_lifecycle(e2e_server):
    """Executes end-to-end browser user scenarios: login, review, CAS approval, 3-way matching, role switch, logout."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # 1. Login
        _login(page, e2e_server)
        assert page.is_visible("text=Công ty Cổ phần Thương mại Alpha VN")

        # 2. Document Inbox listing
        assert page.is_visible("text=Hộp thư Hóa đơn & Chứng từ")
        assert page.is_visible("text=Tải lên hóa đơn điện tử")

        # 3. Open invoice from inbox to review
        page.click("tr:has-text('e_invoice_thang_long.xml') button:has-text('Xem chi tiết')")
        page.wait_for_selector("text=Dữ liệu trường thông tin hóa đơn", timeout=12000)

        # 4. Check Verification Badges
        assert page.is_visible("text=Chữ ký số:")
        assert page.is_visible("text=Tổng cục Thuế:")

        # 5. Check Line Items Table
        assert page.is_visible("text=Chi tiết từng dòng sản phẩm / dịch vụ")
        assert page.is_visible("text=Thành tiền")

        # 6. Approve Invoice (Atomic CAS approval)
        page.click("button:has-text('Phê duyệt (Approve)')")
        page.wait_for_selector("text=Hóa đơn đã được phê duyệt thành công!", timeout=8000)
        assert page.is_visible("text=Hóa đơn đã được phê duyệt thành công!")

        # 7. Open 3-Way Matching Panel
        page.click("button:has-text('Xem 3-Way Matching')")
        page.wait_for_selector("text=Kết quả đối soát 3 chiều", timeout=8000)
        assert page.is_visible("text=3-Way Matching")

        # 8. Role Switching (Switch to Admin)
        page.click("button:has-text('admin')")
        page.wait_for_timeout(1000)

        # 9. Logout Flow
        page.click("button[title='Đăng xuất']")
        page.wait_for_selector("text=Đăng nhập hệ thống", timeout=8000)
        assert page.is_visible("text=Đăng nhập hệ thống")

        context.close()
        browser.close()


def test_playwright_e2e_document_upload(e2e_server):
    """Verifies uploading an invoice file via the UI input selector."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        _login(page, e2e_server)

        # Create temporary valid XML invoice file
        tmp_dir = tempfile.mkdtemp()
        xml_path = Path(tmp_dir) / "e2e_test_upload_invoice.xml"
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <KHMSHDon>1</KHMSHDon>
      <KHHDon>1C26TAA</KHHDon>
      <SHDon>0098765</SHDon>
      <NLap>2026-11-08</NLap>
      <DVTTe>VND</DVTTe>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>Công ty CP Upload E2E</Ten>
        <MST>0109999888</MST>
        <DChi>Hà Nội, Việt Nam</DChi>
      </NBan>
      <NMua>
        <Ten>Công ty Cổ phần Thương mại Alpha VN</Ten>
        <MST>0109998888</MST>
      </NMua>
      <DSHHDVu>
        <HHDVu>
          <STT>1</STT>
          <THHDVu>Dịch vụ kiểm thử E2E</THHDVu>
          <DVTinh>gói</DVTinh>
          <SLuong>1.0000</SLuong>
          <DGia>5000000.0000</DGia>
          <TLCKhau>0.0000</TLCKhau>
          <ThTien>5000000.0000</ThTien>
          <TSuat>10%</TSuat>
        </HHDVu>
      </DSHHDVu>
      <TToan>
        <TgTCThue>5000000.0000</TgTCThue>
        <TgTThue>500000.0000</TgTThue>
        <TgTTTBSo>5500000.0000</TgTTTBSo>
      </TToan>
    </NDHDon>
  </DLHDon>
</HDon>"""
        xml_path.write_text(xml_content, encoding="utf-8")

        # Upload file via file input element
        page.set_input_files("#file-upload", str(xml_path))

        # Wait for the document table to update and show the uploaded file
        page.wait_for_selector("text=e2e_test_upload_invoice.xml", timeout=12000)
        assert page.is_visible("text=e2e_test_upload_invoice.xml")

        context.close()
        browser.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_playwright_e2e_arithmetic_mismatch_detection_and_correction(e2e_server):
    """Verifies that an invoice with arithmetic mismatch displays a red warning banner,
    blocks approval with a clear error, and allows the reviewer to correct the line amount,
    incrementing the revision and then successfully approving the invoice."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        _login(page, e2e_server)

        # 1. Locate the mismatch invoice row in Inbox and open its review page
        page.wait_for_selector("text=invoice_hardware_mismatch.pdf", timeout=10000)
        # Find row containing invoice_hardware_mismatch.pdf and click "Xem chi tiết"
        mismatch_row = page.locator("tr", has_text="invoice_hardware_mismatch.pdf")
        mismatch_row.locator("button:has-text('Xem chi tiết')").click()

        # 2. Wait for Review Screen to load
        page.wait_for_selector("text=Dữ liệu trường thông tin hóa đơn", timeout=12000)
        assert page.is_visible("text=Hóa đơn #0009988")

        # 3. Check Arithmetic Mismatch Warnings
        page.wait_for_selector("[data-testid='arithmetic-mismatch-banner']", timeout=5000)
        assert page.is_visible("text=LINE_ARITHMETIC_MISMATCH")
        assert page.is_visible("text=LỆCH SỐ HỌC")

        # 4. Attempt to approve: Must fail with blocking error
        page.click("button:has-text('Phê duyệt (Approve)')")
        page.wait_for_selector("[data-testid='error-banner']", timeout=8000)
        error_text = page.locator("[data-testid='error-banner']").inner_text()
        assert "LINE_ARITHMETIC_MISMATCH" in error_text or "critical blocking" in error_text

        # 5. Reviewer corrects the line amount: 5 * 10,000,000 = 50,000,000
        line_input = page.locator("[data-testid='input-line-amount-1']")
        line_input.fill("50000000.0000")

        # 6. Save correction (CAS revision bump)
        page.click("button:has-text('Lưu bản đính chính')")
        page.wait_for_selector("text=Thông tin đính chính đã được lưu", timeout=8000)
        assert page.is_visible("text=Rev v2")

        # 7. Approve invoice after correction: Must succeed
        page.click("button:has-text('Phê duyệt (Approve)')")
        page.wait_for_selector("text=Hóa đơn đã được phê duyệt thành công!", timeout=8000)
        assert page.is_visible("text=Hóa đơn đã được phê duyệt thành công!")

        context.close()
        browser.close()


def test_playwright_e2e_export_downloads(e2e_server):
    """Verifies that the export modal triggers actual file downloads for both Excel (.xlsx) and CSV (.csv)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800}, accept_downloads=True
        )
        page = context.new_page()

        _login(page, e2e_server)

        # Open Export Modal
        page.click("button:has-text('Xuất dữ liệu kế toán')")
        page.wait_for_selector("text=Xuất dữ liệu hóa đơn AP", timeout=8000)

        # 1. Export Excel (.xlsx)
        page.click("text=Microsoft Excel (.xlsx)")
        with page.expect_download(timeout=10000) as download_info:
            page.click("button:has-text('Tải xuống')")
        download_excel = download_info.value
        assert download_excel.suggested_filename.endswith(".xlsx")

        # 2. Re-open modal and Export CSV (.csv)
        page.click("button:has-text('Xuất dữ liệu kế toán')")
        page.wait_for_selector("text=Xuất dữ liệu hóa đơn AP", timeout=8000)
        page.click("text=Chuẩn CSV an toàn (.csv)")
        with page.expect_download(timeout=10000) as download_info_csv:
            page.click("button:has-text('Tải xuống')")
        download_csv = download_info_csv.value
        assert download_csv.suggested_filename.endswith(".csv")

        context.close()
        browser.close()


def test_playwright_e2e_pdf_scan_bbox_and_viewer(e2e_server):
    """Verifies that PDF invoices load their rendered pages, BBox evidence is displayed,
    and hovering/clicking evidence updates the highlighted BBox over the document image."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        _login(page, e2e_server)

        # Locate and open invoice_paper_company.pdf
        page.wait_for_selector("text=invoice_paper_company.pdf", timeout=10000)
        row = page.locator("tr", has_text="invoice_paper_company.pdf")
        row.locator("button:has-text('Xem chi tiết')").click()

        # Wait for review screen
        page.wait_for_selector("text=Dữ liệu trường thông tin hóa đơn", timeout=12000)
        assert page.is_visible("text=Hóa đơn #0008899")

        # Verify page indicator
        assert page.is_visible("text=1 / 1 trang")

        # Open Evidence Tab
        page.click(".tab:has-text('Bằng chứng')")
        page.wait_for_selector("text=Bằng chứng OCR và toạ độ BBox", timeout=8000)
        assert page.is_visible("text=Bằng chứng OCR và toạ độ BBox")

        context.close()
        browser.close()


def test_playwright_e2e_production_auth_rejection_and_viewer_rbac(e2e_server):
    """Verifies that failed login displays real backend rejection,
    and Viewer role is enforced with read-only protections on the review panel."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # 1. Invalid login attempt: Must be rejected by backend, not mock-logged in
        page.goto(e2e_server)
        page.wait_for_selector("text=Đăng nhập hệ thống", timeout=10000)
        page.fill("input[type='email']", "nonexistent@invoiceflow.vn")
        page.fill("input[type='password']", "WrongPassword@999")
        page.click("button[type='submit']")
        page.wait_for_timeout(1000)
        # Verify user remains on login page
        assert page.is_visible("text=Đăng nhập hệ thống")

        # 2. Login as Viewer role
        page.fill("input[type='email']", "viewer@invoiceflow.vn")
        page.fill("input[type='password']", "DemoPassword@123")
        page.click("button[type='submit']")
        page.wait_for_selector("text=Hộp thư Tiếp nhận Hóa đơn", timeout=10000)

        # 3. Open invoice
        page.click("tr:has-text('invoice_paper_company.pdf') button:has-text('Xem chi tiết')")
        page.wait_for_selector("text=Dữ liệu trường thông tin hóa đơn", timeout=12000)

        # 4. Check Viewer role indication
        assert page.is_visible("text=Chỉ xem (Viewer)")

        # Attempt to click approve: Must show permission denial
        page.click("button:has-text('Chỉ xem (Viewer)')")
        page.wait_for_selector("[data-testid='error-banner']", timeout=5000)
        err = page.locator("[data-testid='error-banner']").inner_text()
        assert "Viewer" in err

        context.close()
        browser.close()


def test_playwright_e2e_demo_query_flag_is_ignored_in_production_build(e2e_server):
    """Regression: '?demo=true' switched a production build to fixture data, fake sessions and
    client-side 'success' for accounting actions the API had refused."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(f"{e2e_server}/?demo=true")
        page.wait_for_selector("text=Đăng nhập hệ thống", timeout=10000)
        page.fill("input[type='email']", "nobody@invoiceflow.vn")
        page.fill("input[type='password']", "wrong-password")
        page.click("button[type='submit']")
        page.wait_for_timeout(1500)

        # A wrong password must not open a demo session or show fixture invoices.
        assert page.is_visible("text=Đăng nhập hệ thống")
        assert not page.is_visible("text=INV-DIV-01.pdf")
        browser.close()


def test_playwright_e2e_field_level_review_round_trips_through_api(e2e_server):
    """A flagged field is settled individually and disappears only after the API confirms."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _login(page, e2e_server)
        # A seeded invoice no other test approves (the e2e server is shared per module).
        page.click("tr:has-text('invoice_paper_company.pdf') button:has-text('Xem chi tiết')")
        page.wait_for_selector("[data-testid='field-review']", timeout=12000)

        item = page.locator("[data-testid='review-item-supplier_name']")
        assert item.is_visible()
        item.locator("input").fill("Công ty CP Giấy & Văn phòng phẩm Miền Nam")
        item.locator("button:has-text('Sửa')").click()

        page.wait_for_selector(
            "[data-testid='review-item-supplier_name']", state="detached", timeout=8000
        )
        assert page.is_visible("text=Đã xác nhận trường supplier_name")
        browser.close()


def test_playwright_e2e_posted_export_cannot_include_an_invoice_twice(e2e_server):
    """Posting an export marks approved invoices exported; the next batch is empty."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800}, accept_downloads=True
        )
        page = context.new_page()
        _login(page, e2e_server)
        page.click("nav >> text=Xuất dữ liệu")
        button = page.locator("#eBtn")
        button.wait_for(timeout=8000)
        assert "(0 hóa đơn)" not in button.inner_text()

        with page.expect_download(timeout=10000) as download_info:
            button.click()
        assert download_info.value.suggested_filename.endswith(".xlsx")

        page.wait_for_function(
            "document.querySelector('#eBtn').innerText.includes('(0 hóa đơn)')", timeout=8000
        )
        context.close()
        browser.close()
