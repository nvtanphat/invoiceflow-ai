from datetime import date
from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from invoiceflow.api.dependencies import create_access_token
from invoiceflow.api.main import create_app
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    InvoiceLineORM,
    InvoiceORM,
    MembershipORM,
    OutboxEventORM,
    PurchaseOrderLineORM,
    PurchaseOrderORM,
    TenantORM,
    UserORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.security.password import hash_password, verify_password
from invoiceflow.infrastructure.storage.exporter import sanitize_csv_cell


def test_csv_formula_injection_escaping():
    assert sanitize_csv_cell("Normal Supplier") == "Normal Supplier"
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_csv_cell("-5+2") == "'-5+2"


def test_argon2_password_hashing():
    pw = "SuperSecurePassword#2026"
    hashed = hash_password(pw)
    assert hashed.startswith("$argon2id$")
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password(pw, "corrupted_hash") is False
    assert verify_password("", hashed) is False


@pytest.mark.asyncio
async def test_auth_inactive_user_and_revoked_membership():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    active_user_id = str(uuid.uuid4())
    inactive_user_id = str(uuid.uuid4())
    stranger_user_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="Security Test Tenant")
        u_active = UserORM(
            id=active_user_id,
            email="active@security.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Active User",
            is_active=True,
        )
        u_inactive = UserORM(
            id=inactive_user_id,
            email="inactive@security.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Inactive User",
            is_active=False,
        )
        u_stranger = UserORM(
            id=stranger_user_id,
            email="stranger@security.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Stranger User",
            is_active=True,
        )
        m = MembershipORM(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=active_user_id,
            role="reviewer",
        )
        session.add_all([t, u_active, u_inactive, u_stranger, m])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inactive user cannot login
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@security.vn", "password": "Pass123!"},
        )
        assert login_res.status_code == 401

        # Token generated for inactive user is rejected by dependencies
        inactive_token = create_access_token(
            user_id=inactive_user_id,
            tenant_id=tenant_id,
            role="reviewer",
            email="inactive@security.vn",
            settings=settings,
        )
        res = await client.get(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {inactive_token}"},
        )
        assert res.status_code == 401
        assert "inactive" in res.json()["detail"].lower()

        # Token generated for user without tenant membership is rejected by dependencies
        stranger_token = create_access_token(
            user_id=stranger_user_id,
            tenant_id=tenant_id,
            role="reviewer",
            email="stranger@security.vn",
            settings=settings,
        )
        res = await client.get(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
        assert res.status_code == 403
        assert (
            "revoked" in res.json()["detail"].lower() or "not found" in res.json()["detail"].lower()
        )

    await db_manager.close()


@pytest.mark.asyncio
async def test_separation_of_duties_uploader_cannot_approve():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    uploader_id = str(uuid.uuid4())
    approver_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    invoice_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="SoD Tenant")
        u_uploader = UserORM(
            id=uploader_id,
            email="uploader@sod.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Uploader User",
            is_active=True,
        )
        u_approver = UserORM(
            id=approver_id,
            email="approver@sod.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Approver User",
            is_active=True,
        )
        m1 = MembershipORM(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=uploader_id, role="accountant"
        )
        m2 = MembershipORM(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=approver_id, role="accountant"
        )
        doc = DocumentORM(
            id=doc_id,
            tenant_id=tenant_id,
            filename="test_inv.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            sha256="abc123sha",
            storage_uri="local://test_inv.pdf",
            status="READY",
            uploaded_by=uploader_id,
        )
        inv = InvoiceORM(
            id=invoice_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0101234567",
            supplier_name="Vendor A",
            subtotal=Decimal("1000000"),
            tax_total=Decimal("100000"),
            amount_payable=Decimal("1100000"),
        )
        session.add_all([t, u_uploader, u_approver, m1, m2, doc, inv])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    uploader_token = create_access_token(
        user_id=uploader_id,
        tenant_id=tenant_id,
        role="accountant",
        email="uploader@sod.vn",
        settings=settings,
    )
    approver_token = create_access_token(
        user_id=approver_id,
        tenant_id=tenant_id,
        role="accountant",
        email="approver@sod.vn",
        settings=settings,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Uploader attempts to approve own uploaded invoice -> 403 Forbidden (SoD)
        fail_res = await client.post(
            f"/api/v1/invoices/{invoice_id}/review",
            headers={"Authorization": f"Bearer {uploader_token}", "If-Match": '"1"'},
            json={"action": "approve", "notes": "Self approval attempt"},
        )
        assert fail_res.status_code == 403
        assert "separation of duties" in fail_res.json()["detail"].lower()

        # 2. Independent approver approves the invoice -> 200 OK
        ok_res = await client.post(
            f"/api/v1/invoices/{invoice_id}/review",
            headers={"Authorization": f"Bearer {approver_token}", "If-Match": '"1"'},
            json={"action": "approve", "notes": "Independent approval"},
        )
        assert ok_res.status_code == 200
        assert ok_res.json()["status"] == "APPROVED"
        assert ok_res.json()["revision"] == 2

    await db_manager.close()


@pytest.mark.asyncio
async def test_cross_tenant_grn_isolation():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    po_a_id = str(uuid.uuid4())
    po_line_a_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t_a = TenantORM(id=tenant_a, name="Tenant A")
        t_b = TenantORM(id=tenant_b, name="Tenant B")
        u_b = UserORM(
            id=user_b_id,
            email="user_b@tenantb.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="User B",
            is_active=True,
        )
        m_b = MembershipORM(
            id=str(uuid.uuid4()), tenant_id=tenant_b, user_id=user_b_id, role="accountant"
        )
        po_a = PurchaseOrderORM(
            id=po_a_id,
            tenant_id=tenant_a,
            vendor_tax_id="0101234567",
            vendor_name="Vendor A",
            po_number="PO-TENANT-A-001",
            order_date=date(2026, 1, 15),
            currency="VND",
            subtotal=Decimal("5000000"),
        )
        po_line_a = PurchaseOrderLineORM(
            id=po_line_a_id,
            po_id=po_a_id,
            line_no=1,
            sku="SKU-001",
            description="Item from Tenant A",
            ordered_qty=Decimal("10"),
            unit_price=Decimal("500000"),
            line_total=Decimal("5000000"),
        )
        session.add_all([t_a, t_b, u_b, m_b, po_a, po_line_a])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    user_b_token = create_access_token(
        user_id=user_b_id,
        tenant_id=tenant_b,
        role="accountant",
        email="user_b@tenantb.vn",
        settings=settings,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Tenant B attempts to create GRN linked to PO from Tenant A -> 404 Not Found
        res = await client.post(
            "/api/v1/goods-receipts",
            headers={"Authorization": f"Bearer {user_b_token}"},
            json={
                "po_id": po_a_id,
                "grn_number": "GRN-ATTACK-001",
                "receipt_date": "2026-01-20",
                "lines": [
                    {
                        "po_line_id": po_line_a_id,
                        "line_no": 1,
                        "received_qty": "10",
                        "rejected_qty": "0",
                    }
                ],
            },
        )
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    await db_manager.close()


@pytest.mark.asyncio
async def test_export_invoices_decimal_preservation():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    inv_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="Export Tenant")
        u = UserORM(
            id=user_id,
            email="export@tenant.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Export User",
            is_active=True,
        )
        m = MembershipORM(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, role="accountant"
        )
        doc = DocumentORM(
            id=doc_id,
            tenant_id=tenant_id,
            filename="export_inv.pdf",
            mime_type="application/pdf",
            file_size_bytes=2048,
            sha256="shaexport123",
            storage_uri="local://export_inv.pdf",
            status="READY",
        )
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            revision=1,
            status="APPROVED",
            supplier_tax_id="0312345678",
            supplier_name="Công Ty TNHH Dịch Vụ Kế Toán",
            invoice_number="INV-2026-999",
            invoice_series="1C26TAA",
            issue_date=date(2026, 2, 1),
            currency="VND",
            subtotal=Decimal("1234567.8900"),
            tax_total=Decimal("123456.7900"),
            amount_payable=Decimal("1358024.6800"),
        )
        session.add_all([t, u, m, doc, inv])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="accountant",
        email="export@tenant.vn",
        settings=settings,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test JSON export format
        res_json = await client.get(
            "/api/v1/exports/invoices?format=json",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_json.status_code == 200
        data = res_json.json()
        assert len(data) == 1
        assert Decimal(str(data[0]["subtotal"])) == Decimal("1234567.8900")
        assert Decimal(str(data[0]["amount_payable"])) == Decimal("1358024.6800")

        # Test CSV export format
        res_csv = await client.get(
            "/api/v1/exports/invoices?format=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_csv.status_code == 200
        csv_text = res_csv.text
        assert "INV-2026-999" in csv_text
        assert "1234567.89" in csv_text or "1234567.8900" in csv_text
        assert "1358024.68" in csv_text or "1358024.6800" in csv_text

    await db_manager.close()


@pytest.mark.asyncio
async def test_unified_review_actions_and_concurrency():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    inv_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="Review Tenant")
        u = UserORM(
            id=reviewer_id,
            email="reviewer@test.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Reviewer User",
            is_active=True,
        )
        m = MembershipORM(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=reviewer_id, role="reviewer"
        )
        doc = DocumentORM(
            id=doc_id,
            tenant_id=tenant_id,
            filename="review_inv.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            sha256="shatest456",
            storage_uri="local://review_inv.pdf",
            status="READY",
            uploaded_by="different_uploader_id",
        )
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0109999999",
            supplier_name="Old Vendor Name",
            subtotal=Decimal("500000"),
            tax_total=Decimal("50000"),
            amount_payable=Decimal("550000"),
        )
        session.add_all([t, u, m, doc, inv])

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    token = create_access_token(
        user_id=reviewer_id,
        tenant_id=tenant_id,
        role="reviewer",
        email="reviewer@test.vn",
        settings=settings,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Action "correct": update supplier_name with valid revision 1
        res_correct = await client.post(
            f"/api/v1/invoices/{inv_id}/review",
            headers={"Authorization": f"Bearer {token}", "If-Match": '"1"'},
            json={
                "action": "correct",
                "corrections": {"supplier_name": "Corrected Vendor Name"},
                "reason": "Name spelling corrected",
            },
        )
        assert res_correct.status_code == 200
        assert res_correct.json()["revision"] == 2

        # 2. Concurrency Conflict: try to modify using stale revision 1 -> 409 Conflict
        res_stale = await client.post(
            f"/api/v1/invoices/{inv_id}/review",
            headers={"Authorization": f"Bearer {token}", "If-Match": '"1"'},
            json={"action": "reject", "reason": "Late rejection with stale revision"},
        )
        assert res_stale.status_code == 409

        # 3. Action "reject" with fresh revision 2 -> 200 OK
        res_reject = await client.post(
            f"/api/v1/invoices/{inv_id}/review",
            headers={"Authorization": f"Bearer {token}", "If-Match": '"2"'},
            json={"action": "reject", "reason": "Vendor tax ID mismatch"},
        )
        assert res_reject.status_code == 200
        assert res_reject.json()["status"] == "REJECTED"
        assert res_reject.json()["revision"] == 3

    await db_manager.close()


@pytest.mark.asyncio
async def test_outbox_dispatcher_retries_on_broker_failure(monkeypatch):
    from invoiceflow.application.ingestion.outbox_dispatcher import OutboxDispatcher

    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    event_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        evt = OutboxEventORM(
            id=event_id,
            tenant_id=tenant_id,
            topic="document.received",
            aggregate_id=job_id,
            payload_json='{"job_id": "test"}',
            is_published=False,
        )
        session.add(evt)

    dispatcher = OutboxDispatcher(db_manager)

    # 1. Simulate Redis broker connection failure
    def mock_send_fail(*args, **kwargs):
        raise ConnectionError("Redis connection lost")

    from invoiceflow.workers import actors

    monkeypatch.setattr(actors.process_document_job, "send", mock_send_fail)

    dispatched = await dispatcher.dispatch_pending_events(limit=10)
    assert dispatched == 0

    # Verify event remains unpublished
    async with db_manager.session() as session:
        stored = await session.get(OutboxEventORM, event_id)
        assert stored.is_published is False

    # 2. Simulate broker connection restored
    send_calls = []

    def mock_send_ok(msg_job_id):
        send_calls.append(msg_job_id)

    monkeypatch.setattr(actors.process_document_job, "send", mock_send_ok)

    dispatched_recovered = await dispatcher.dispatch_pending_events(limit=10)
    assert dispatched_recovered == 1
    assert send_calls == [job_id]

    # Verify event is now marked published
    async with db_manager.session() as session:
        stored = await session.get(OutboxEventORM, event_id)
        assert stored.is_published is True

    await db_manager.close()


def test_production_security_rejects_default_jwt_secret():
    from invoiceflow.config import Settings

    # In production, default insecure secrets must fail immediately
    with pytest.raises(ValueError) as excinfo:
        Settings(
            APP_ENV="production",
            JWT_SECRET="dev-insecure-secret-key-must-be-changed-in-production-32-chars",
        )
    assert "strong non-default JWT_SECRET is strictly required" in str(excinfo.value)

    # Strong custom secret passes in production
    valid_settings = Settings(
        APP_ENV="production",
        JWT_SECRET="ProductionVeryStrongSecretKey_9876543210_SecureToken",
    )
    assert valid_settings.APP_ENV == "production"


@pytest.mark.asyncio
async def test_financial_arithmetic_mismatch_blocks_approval_until_corrected():
    db_url = "sqlite+aiosqlite:///:memory:"
    db_manager = DatabaseSessionManager(database_url=db_url)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    inv_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        t = TenantORM(id=tenant_id, name="Finance Safety Tenant")
        u = UserORM(
            id=reviewer_id,
            email="fin_reviewer@test.vn",
            hashed_password=hash_password("Pass123!"),
            full_name="Finance Reviewer",
            is_active=True,
        )
        m = MembershipORM(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=reviewer_id, role="reviewer"
        )
        doc = DocumentORM(
            id=doc_id,
            tenant_id=tenant_id,
            filename="arithmetic_error.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            sha256="shafinance123",
            storage_uri="local://arithmetic_error.pdf",
            status="READY",
            uploaded_by="different_uploader_id",
        )
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0109999999",
            supplier_name="Vendor Name",
            invoice_number="INV-001",
            subtotal=Decimal("40000000.0000"),
            tax_total=Decimal("0.0000"),
            amount_payable=Decimal("40000000.0000"),
        )
        # Line with arithmetic error: qty=5 * unit_price=10,000,000 != line_amount=40,000,000
        inv_line = InvoiceLineORM(
            id=str(uuid.uuid4()),
            invoice_id=inv_id,
            line_no=1,
            description="Laptop Dell",
            qty=Decimal("5.0000"),
            unit_price=Decimal("10000000.0000"),
            discount=Decimal("0.0000"),
            line_amount=Decimal("40000000.0000"),
        )
        session.add_all([t, u, m, doc, inv, inv_line])
        await session.flush()

        from invoiceflow.application.reconciliation.service import ReconciliationService
        from invoiceflow.domain.invoices.models import (
            InvoiceAggregate,
            InvoiceLine,
            InvoiceStatus,
            VerificationStatus,
        )

        reconcile_agg = InvoiceAggregate(
            id=inv.id,
            tenant_id=inv.tenant_id,
            document_id=inv.document_id,
            revision=inv.revision,
            status=InvoiceStatus(inv.status),
            supplier_tax_id=inv.supplier_tax_id,
            supplier_name=inv.supplier_name,
            invoice_number=inv.invoice_number,
            subtotal=inv.subtotal,
            amount_payable=inv.amount_payable,
            lines=[
                InvoiceLine(
                    line_no=inv_line.line_no,
                    description=inv_line.description,
                    qty=inv_line.qty,
                    unit_price=inv_line.unit_price,
                    discount=inv_line.discount,
                    line_amount=inv_line.line_amount,
                )
            ],
            signature_status=VerificationStatus(inv.signature_status),
            tax_authority_status=VerificationStatus(inv.tax_authority_status),
        )
        reconciliation = ReconciliationService(session)
        await reconciliation.reconcile_invoice(reconcile_agg)

    app = create_app(database_url=db_url, db_manager=db_manager)
    transport = ASGITransport(app=app)
    settings = get_settings()

    token = create_access_token(
        user_id=reviewer_id,
        tenant_id=tenant_id,
        role="reviewer",
        email="fin_reviewer@test.vn",
        settings=settings,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Attempting to approve invoice with arithmetic mismatch MUST fail (blocking)
        res_fail = await client.post(
            f"/api/v1/invoices/{inv_id}/review",
            headers={"Authorization": f"Bearer {token}", "If-Match": '"1"'},
            json={"action": "approve", "notes": "Trying to bypass arithmetic error"},
        )
        assert res_fail.status_code in (400, 422)
        assert (
            "LINE_ARITHMETIC_MISMATCH" in res_fail.json()["detail"]
            or "nghiêm trọng" in res_fail.json()["detail"]
        )

        # 2. Correct the line amount arithmetic
        res_correct = await client.post(
            f"/api/v1/invoices/{inv_id}/review",
            headers={"Authorization": f"Bearer {token}", "If-Match": '"1"'},
            json={
                "action": "correct",
                "corrections": {
                    "lines": [{"line_no": 1, "line_amount": "50000000"}],
                    "subtotal": "50000000",
                    "amount_payable": "50000000",
                },
                "reason": "Corrected line 1 calculation error",
            },
        )
        assert res_correct.status_code == 200
        assert res_correct.json()["revision"] == 2

        # 3. Now approval SUCCEEDS
        res_approve = await client.post(
            f"/api/v1/invoices/{inv_id}/review",
            headers={"Authorization": f"Bearer {token}", "If-Match": '"2"'},
            json={"action": "approve", "notes": "Approved after correction"},
        )
        assert res_approve.status_code == 200
        assert res_approve.json()["status"] == "APPROVED"
        assert res_approve.json()["revision"] == 3

    await db_manager.close()
