import pytest
import uuid
from decimal import Decimal
from datetime import date


@pytest.mark.asyncio
async def test_database_tenant_isolation_and_repositories():
    from invoiceflow.infrastructure.database.session import DatabaseSessionManager
    from invoiceflow.infrastructure.database.base import Base
    from invoiceflow.infrastructure.database.repositories import (
        TenantRepository,
        DocumentRepository,
        InvoiceRepository,
    )
    from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceStatus

    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    async with db_manager.session() as session:
        tenant_repo = TenantRepository(session)
        doc_repo = DocumentRepository(session)
        inv_repo = InvoiceRepository(session)

        # 1. Create two distinct tenants
        tenant_a = await tenant_repo.create_tenant(name="Công ty A")
        tenant_b = await tenant_repo.create_tenant(name="Công ty B")
        assert tenant_a.id != tenant_b.id

        # 2. Create document under Tenant A
        doc_a = await doc_repo.create_document(
            tenant_id=tenant_a.id,
            filename="invoice_a.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            sha256="a" * 64,
            storage_uri="local://data/invoice_a.pdf",
        )
        assert doc_a.tenant_id == tenant_a.id

        # 3. Tenant isolation check: Tenant B cannot access Tenant A's document
        found_by_b = await doc_repo.get_document(tenant_id=tenant_b.id, document_id=doc_a.id)
        assert found_by_b is None

        found_by_a = await doc_repo.get_document(tenant_id=tenant_a.id, document_id=doc_a.id)
        assert found_by_a is not None
        assert found_by_a.id == doc_a.id

        # 4. Save Invoice Aggregate under Tenant A
        invoice = InvoiceAggregate(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            document_id=doc_a.id,
            revision=1,
            status=InvoiceStatus.READY_FOR_REVIEW,
            supplier_tax_id="0109999999",
            supplier_name="Nhà cung cấp X",
            invoice_number="INV-099",
            invoice_series="1C26TAA",
            issue_date=date(2026, 11, 8),
            currency="VND",
            subtotal=Decimal("100000.0000"),
            tax_total=Decimal("10000.0000"),
            amount_payable=Decimal("110000.0000"),
        )
        saved_inv = await inv_repo.create_invoice(invoice)
        assert saved_inv.revision == 1

        # 5. Optimistic locking check: update with mismatched revision fails
        updated = await inv_repo.update_invoice_status(
            tenant_id=tenant_a.id,
            invoice_id=invoice.id,
            expected_revision=1,
            new_status=InvoiceStatus.APPROVED,
        )
        assert updated is not None
        assert updated.revision == 2
        assert updated.status == InvoiceStatus.APPROVED

        # Stale update with revision 1 must return None (concurrency conflict)
        stale_update = await inv_repo.update_invoice_status(
            tenant_id=tenant_a.id,
            invoice_id=invoice.id,
            expected_revision=1,
            new_status=InvoiceStatus.REJECTED,
        )
        assert stale_update is None

    await db_manager.close()
