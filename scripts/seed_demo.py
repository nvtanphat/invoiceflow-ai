import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
import uuid

# Ensure src/ is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    GoodsReceiptLineORM,
    GoodsReceiptORM,
    InvoiceLineORM,
    InvoiceORM,
    MembershipORM,
    PurchaseOrderLineORM,
    PurchaseOrderORM,
    TenantORM,
    TolerancePolicyORM,
    UserORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.security.password import hash_password


async def seed_all(db_manager: DatabaseSessionManager) -> None:
    async with db_manager.session() as session:
        # 1. Tenants
        t1_id = "tenant-alpha-001"
        t2_id = "tenant-beta-002"

        t1 = await session.get(TenantORM, t1_id)
        if not t1:
            t1 = TenantORM(id=t1_id, name="Công ty Cổ phần Thương mại Alpha VN")
            session.add(t1)

        t2 = await session.get(TenantORM, t2_id)
        if not t2:
            t2 = TenantORM(id=t2_id, name="Tập đoàn Phân phối Quốc tế Beta")
            session.add(t2)

        # 2. Users & Memberships
        default_pwd_hash = hash_password("DemoPassword@123")
        users_meta = [
            ("user-admin-01", "admin@invoiceflow.vn", "Hệ thống Admin", "admin", t1_id),
            ("user-accountant-02", "accountant@invoiceflow.vn", "Kế toán viên Nguyễn Văn An", "accountant", t1_id),
            ("user-reviewer-03", "reviewer@invoiceflow.vn", "Kiểm soát viên Trần Thị Bình", "reviewer", t1_id),
            ("user-viewer-04", "viewer@invoiceflow.vn", "Giám đốc Tài chính Lê Văn C", "viewer", t1_id),
        ]

        for u_id, email, name, role, tenant_id in users_meta:
            stmt = select(UserORM).where(UserORM.email == email)
            existing_user = (await session.execute(stmt)).scalar_one_or_none()
            if not existing_user:
                user = UserORM(
                    id=u_id,
                    email=email,
                    hashed_password=default_pwd_hash,
                    full_name=name,
                    is_active=True,
                )
                session.add(user)
                membership = MembershipORM(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    user_id=u_id,
                    role=role,
                )
                session.add(membership)

        # 3. Tolerance Policies
        p1 = (await session.execute(
            select(TolerancePolicyORM).where(TolerancePolicyORM.tenant_id == t1_id)
        )).scalars().first()
        if not p1:
            policy1 = TolerancePolicyORM(
                id=str(uuid.uuid4()),
                tenant_id=t1_id,
                price_tolerance_pct=Decimal("0.02"),
                qty_tolerance_pct=Decimal("0.00"),
                max_amount_delta=Decimal("50000.0000"),
                auto_approve_threshold=Decimal("20000000.0000"),
                separation_of_duties_required=True,
                effective_from=date(2026, 1, 1),
            )
            session.add(policy1)

        # 4. Purchase Orders and Lines
        po1_id = "po-2026-001"
        existing_po1 = await session.get(PurchaseOrderORM, po1_id)
        if not existing_po1:
            po1 = PurchaseOrderORM(
                id=po1_id,
                tenant_id=t1_id,
                vendor_tax_id="0101234567",
                vendor_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
                po_number="PO-2026-001",
                order_date=date(2026, 3, 1),
                currency="VND",
                subtotal=Decimal("50000000.0000"),
            )
            session.add(po1)
            line1 = PurchaseOrderLineORM(
                id="po-line-001",
                po_id=po1_id,
                line_no=1,
                sku="DELL-XPS-13",
                description="Máy tính xách tay Dell XPS 13 i7/16GB/512GB",
                unit="cái",
                ordered_qty=Decimal("5.0000"),
                unit_price=Decimal("10000000.0000"),
                line_total=Decimal("50000000.0000"),
            )
            session.add(line1)

        po2_id = "po-2026-002"
        existing_po2 = await session.get(PurchaseOrderORM, po2_id)
        if not existing_po2:
            po2 = PurchaseOrderORM(
                id=po2_id,
                tenant_id=t1_id,
                vendor_tax_id="0309876543",
                vendor_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
                po_number="PO-2026-002",
                order_date=date(2026, 3, 5),
                currency="VND",
                subtotal=Decimal("12000000.0000"),
            )
            session.add(po2)
            line2 = PurchaseOrderLineORM(
                id="po-line-002",
                po_id=po2_id,
                line_no=1,
                sku="PAPER-A4-70",
                description="Giấy photocopy Double A A4 70gsm",
                unit="ram",
                ordered_qty=Decimal("200.0000"),
                unit_price=Decimal("60000.0000"),
                line_total=Decimal("12000000.0000"),
            )
            session.add(line2)

        # 5. Goods Receipts (GRN)
        grn1_id = "grn-2026-001"
        existing_grn1 = await session.get(GoodsReceiptORM, grn1_id)
        if not existing_grn1:
            grn1 = GoodsReceiptORM(
                id=grn1_id,
                tenant_id=t1_id,
                po_id=po1_id,
                grn_number="GRN-2026-001",
                receipt_date=date(2026, 3, 2),
            )
            session.add(grn1)
            grn_line1 = GoodsReceiptLineORM(
                id="grn-line-001",
                grn_id=grn1_id,
                po_line_id="po-line-001",
                line_no=1,
                received_qty=Decimal("5.0000"),
                rejected_qty=Decimal("0.0000"),
            )
            session.add(grn_line1)

        # 6. Sample Documents and Invoices
        doc1_id = "doc-demo-xml-001"
        existing_doc1 = await session.get(DocumentORM, doc1_id)
        if not existing_doc1:
            doc1 = DocumentORM(
                id=doc1_id,
                tenant_id=t1_id,
                filename="e_invoice_thang_long.xml",
                mime_type="application/xml",
                file_size_bytes=4096,
                sha256=hashlib.sha256(b"sample_xml_bytes").hexdigest(),
                storage_uri=f"tenants/{t1_id}/documents/{doc1_id}.xml",
                status="PROCESSED",
                page_count=1,
            )
            session.add(doc1)

            inv1 = InvoiceORM(
                id="inv-demo-001",
                tenant_id=t1_id,
                document_id=doc1_id,
                revision=1,
                status="MATCHED",
                supplier_tax_id="0101234567",
                supplier_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
                buyer_tax_id="0109998888",
                buyer_name="Công ty Cổ phần Thương mại Alpha VN",
                invoice_number="0001245",
                invoice_series="1C26TAA",
                issue_date=date(2026, 3, 2),
                currency="VND",
                subtotal=Decimal("50000000.0000"),
                discount_total=Decimal("0.0000"),
                tax_total=Decimal("5000000.0000"),
                amount_payable=Decimal("55000000.0000"),
                rounding_adjustment=Decimal("0.0000"),
                signature_status="valid",
                tax_authority_status="verified",
            )
            session.add(inv1)

            inv_line1 = InvoiceLineORM(
                id="inv-line-001",
                invoice_id="inv-demo-001",
                line_no=1,
                sku_ref="DELL-XPS-13",
                description="Máy tính xách tay Dell XPS 13 i7/16GB/512GB",
                unit="cái",
                qty=Decimal("5.0000"),
                unit_price=Decimal("10000000.0000"),
                discount=Decimal("0.0000"),
                tax_rate=Decimal("10.00"),
                tax=Decimal("5000000.0000"),
                line_amount=Decimal("50000000.0000"),
            )
            session.add(inv_line1)

        doc2_id = "doc-demo-pdf-002"
        existing_doc2 = await session.get(DocumentORM, doc2_id)
        if not existing_doc2:
            doc2 = DocumentORM(
                id=doc2_id,
                tenant_id=t1_id,
                filename="invoice_paper_company.pdf",
                mime_type="application/pdf",
                file_size_bytes=32768,
                sha256=hashlib.sha256(b"sample_pdf_bytes").hexdigest(),
                storage_uri=f"tenants/{t1_id}/documents/{doc2_id}.pdf",
                status="READY_FOR_REVIEW",
                page_count=1,
            )
            session.add(doc2)

            inv2 = InvoiceORM(
                id="inv-demo-002",
                tenant_id=t1_id,
                document_id=doc2_id,
                revision=1,
                status="PENDING_REVIEW",
                supplier_tax_id="0309876543",
                supplier_name="Công ty CP Giấy & Văn phòng phẩm Miền Nam",
                buyer_tax_id="0109998888",
                buyer_name="Công ty Cổ phần Thương mại Alpha VN",
                invoice_number="0008899",
                invoice_series="2C26TBB",
                issue_date=date(2026, 3, 6),
                currency="VND",
                subtotal=Decimal("12600000.0000"),
                discount_total=Decimal("0.0000"),
                tax_total=Decimal("1008000.0000"),
                amount_payable=Decimal("13608000.0000"),
                rounding_adjustment=Decimal("0.0000"),
                signature_status="unverified",
                tax_authority_status="not_checked",
            )
            session.add(inv2)

            inv_line2 = InvoiceLineORM(
                id="inv-line-002",
                invoice_id="inv-demo-002",
                line_no=1,
                sku_ref="PAPER-A4-70",
                description="Giấy photocopy Double A A4 70gsm (lệch giá 5%)",
                unit="ram",
                qty=Decimal("200.0000"),
                unit_price=Decimal("63000.0000"),
                discount=Decimal("0.0000"),
                tax_rate=Decimal("8.00"),
                tax=Decimal("1008000.0000"),
                line_amount=Decimal("12600000.0000"),
            )
            session.add(inv_line2)

        await session.commit()


async def main() -> None:
    settings = get_settings()
    db_manager = DatabaseSessionManager(database_url=settings.DATABASE_URL, echo=settings.DEBUG)
    await db_manager.create_tables()
    print("Database tables initialized.")
    await seed_all(db_manager)
    print("Demo dataset seeded successfully.")
    await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
