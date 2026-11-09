import json
import uuid
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceStatus
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    FieldEvidenceORM,
    InvoiceLineORM,
    InvoiceORM,
    TenantORM,
)


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_tenant(self, name: str) -> TenantORM:
        tenant = TenantORM(id=str(uuid.uuid4()), name=name)
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def get_tenant(self, tenant_id: UUID | str) -> Optional[TenantORM]:
        stmt = select(TenantORM).where(TenantORM.id == str(tenant_id))
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_document(
        self,
        tenant_id: UUID | str,
        filename: str,
        mime_type: str,
        file_size_bytes: int,
        sha256: str,
        storage_uri: str,
        page_count: int = 1,
        uploaded_by: Optional[str] = None,
    ) -> DocumentORM:
        doc = DocumentORM(
            id=str(uuid.uuid4()),
            tenant_id=str(tenant_id),
            filename=filename,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            sha256=sha256,
            storage_uri=storage_uri,
            page_count=page_count,
            status="RECEIVED",
            uploaded_by=uploaded_by,
        )
        self._session.add(doc)
        await self._session.flush()
        return doc

    async def get_document(
        self, tenant_id: UUID | str, document_id: UUID | str
    ) -> Optional[DocumentORM]:
        stmt = select(DocumentORM).where(
            DocumentORM.tenant_id == str(tenant_id),
            DocumentORM.id == str(document_id),
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def find_by_sha256(self, tenant_id: UUID | str, sha256: str) -> Optional[DocumentORM]:
        stmt = select(DocumentORM).where(
            DocumentORM.tenant_id == str(tenant_id),
            DocumentORM.sha256 == sha256,
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()


class InvoiceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_invoice_by_document(
        self, tenant_id: UUID | str, document_id: UUID | str
    ) -> Optional[InvoiceORM]:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(InvoiceORM)
            .options(selectinload(InvoiceORM.lines), selectinload(InvoiceORM.evidence))
            .where(
                InvoiceORM.tenant_id == str(tenant_id),
                InvoiceORM.document_id == str(document_id),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_invoice(self, aggregate: InvoiceAggregate) -> InvoiceORM:
        # Idempotency check: if invoice already created for this document, return existing
        existing = await self.get_invoice_by_document(aggregate.tenant_id, aggregate.document_id)
        if existing:
            return existing

        inv = InvoiceORM(
            id=str(aggregate.id),
            tenant_id=str(aggregate.tenant_id),
            document_id=str(aggregate.document_id),
            revision=aggregate.revision,
            status=aggregate.status.value,
            supplier_tax_id=aggregate.supplier_tax_id,
            supplier_name=aggregate.supplier_name,
            buyer_tax_id=aggregate.buyer_tax_id,
            buyer_name=aggregate.buyer_name,
            invoice_number=aggregate.invoice_number,
            invoice_series=aggregate.invoice_series,
            issue_date=aggregate.issue_date,
            currency=aggregate.currency,
            exchange_rate=aggregate.exchange_rate,
            subtotal=aggregate.subtotal,
            discount_total=aggregate.discount_total,
            tax_total=aggregate.tax_total,
            amount_payable=aggregate.amount_payable,
            rounding_adjustment=aggregate.rounding_adjustment,
            signature_status=aggregate.signature_status.value,
            tax_authority_status=aggregate.tax_authority_status.value,
        )
        self._session.add(inv)
        await self._session.flush()

        for line in aggregate.lines:
            line_orm = InvoiceLineORM(
                id=str(uuid.uuid4()),
                invoice_id=inv.id,
                line_no=line.line_no,
                sku_ref=line.sku_ref,
                description=line.description,
                unit=line.unit,
                qty=line.qty,
                unit_price=line.unit_price,
                discount=line.discount,
                tax_rate=line.tax_rate,
                tax=line.tax,
                line_amount=line.line_amount,
                po_line_id=str(line.purchase_order_line_id)
                if line.purchase_order_line_id
                else None,
            )
            self._session.add(line_orm)

        for ev in aggregate.evidence:
            ev_orm = FieldEvidenceORM(
                id=str(uuid.uuid4()),
                invoice_id=inv.id,
                field_path=ev.field_path,
                source_kind=ev.source_kind,
                page_index=ev.page_index,
                bbox_json=json.dumps(ev.bbox.model_dump()) if ev.bbox else None,
                table_id=ev.table_id,
                cell_id=ev.cell_id,
                raw_value=ev.raw_value,
                normalized_value=ev.normalized_value,
                confidence=ev.confidence,
                extractor=ev.extractor,
                verification_state=getattr(ev, "verification_state", "model_proposed"),
            )
            self._session.add(ev_orm)

        await self._session.flush()
        return inv

    async def get_invoice(
        self, tenant_id: UUID | str, invoice_id: UUID | str
    ) -> Optional[InvoiceORM]:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(InvoiceORM)
            .options(selectinload(InvoiceORM.lines), selectinload(InvoiceORM.evidence))
            .where(
                InvoiceORM.tenant_id == str(tenant_id),
                InvoiceORM.id == str(invoice_id),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_invoices(
        self, tenant_id: UUID | str, limit: int = 50, offset: int = 0
    ) -> List[InvoiceORM]:
        stmt = (
            select(InvoiceORM)
            .where(InvoiceORM.tenant_id == str(tenant_id))
            .order_by(InvoiceORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_invoice_status(
        self,
        tenant_id: UUID | str,
        invoice_id: UUID | str,
        expected_revision: int,
        new_status: InvoiceStatus,
    ) -> Optional[InvoiceORM]:
        stmt = (
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == str(tenant_id),
                InvoiceORM.id == str(invoice_id),
                InvoiceORM.revision == expected_revision,
            )
            .values(
                status=new_status.value,
                revision=expected_revision + 1,
            )
            .returning(InvoiceORM)
        )
        res = await self._session.execute(stmt)
        updated = res.scalar_one_or_none()
        await self._session.flush()
        return updated
