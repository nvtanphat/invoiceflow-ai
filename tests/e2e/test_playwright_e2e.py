from pathlib import Path
import shutil
import tempfile
import threading
import time
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright
import pytest
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
        pytest.skip("Frontend production build dist/ not found. Run 'pnpm --prefix apps/web build' first.")

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


def test_playwright_e2e_full_lifecycle(e2e_server):
    """Executes end-to-end browser user scenarios using Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # 1. Navigation to Login Screen
        page.goto(e2e_server)
        page.wait_for_selector("text=Đăng nhập hệ thống", timeout=8000)
        assert page.is_visible("text=InvoiceFlow AI")

        # 2. Login as Accountant
        page.fill("input[type='email']", "accountant@invoiceflow.vn")
        page.fill("input[type='password']", "DemoPassword@123")
        page.click("button[type='submit']")

        # Wait for dashboard to load
        page.wait_for_selector("text=Hộp thư Tiếp nhận Hóa đơn", timeout=8000)
        assert page.is_visible("text=Công ty Cổ phần Thương mại Alpha VN")

        # 3. Document Inbox listing
        assert page.is_visible("text=Hộp thư Hóa đơn & Chứng từ")
        assert page.is_visible("text=Tải lên hóa đơn điện tử")

        # 4. Switch to Review Tab
        page.click("button:has-text('Xem xét & Phê duyệt')")
        page.wait_for_selector("text=Dữ liệu trường thông tin hóa đơn", timeout=12000)

        # 5. Check Verification Badges
        assert page.is_visible("text=Chữ ký số:")
        assert page.is_visible("text=Tổng cục Thuế:")

        # 6. Check Line Items Table
        assert page.is_visible("text=Chi tiết từng dòng sản phẩm / dịch vụ")
        assert page.is_visible("text=Thành tiền")

        # 7. Approve Invoice (Atomic CAS approval)
        page.click("button:has-text('Phê duyệt (Approve)')")
        page.wait_for_selector("text=Hóa đơn đã được phê duyệt thành công!", timeout=8000)
        assert page.is_visible("text=Hóa đơn đã được phê duyệt thành công!")

        # 8. Open 3-Way Matching Panel
        page.click("button:has-text('Xem 3-Way Matching')")
        page.wait_for_selector("text=Kết quả đối soát 3 chiều", timeout=8000)
        assert page.is_visible("text=3-Way Matching")

        # 9. Open Export Modal
        page.click("button:has-text('Xuất dữ liệu kế toán')")
        page.wait_for_selector("text=Xuất dữ liệu hóa đơn AP", timeout=8000)
        assert page.is_visible("text=Microsoft Excel (.xlsx)")
        assert page.is_visible("text=Chuẩn CSV an toàn (.csv)")
        assert page.is_visible("text=Structured JSON (.json)")

        # Close export modal
        page.click("button:has-text('Hủy')")

        # 10. Role Switching (Switch to Admin)
        page.click("button:has-text('admin')")
        page.wait_for_timeout(1000)

        # 11. Logout Flow
        page.click("button[title='Đăng xuất']")
        page.wait_for_selector("text=Đăng nhập hệ thống", timeout=8000)
        assert page.is_visible("text=Đăng nhập hệ thống")

        context.close()
        browser.close()
