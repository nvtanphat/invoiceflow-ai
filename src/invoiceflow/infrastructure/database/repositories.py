from datetime import date
import json
import uuid
from typing import List, Optional
from uuid import UUID
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from invoiceflow.domain.invoices.models import (
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
    VerificationStatus,
)
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import (
    GoodsReceipt,
    GRNLine,
    POLine,
    PurchaseOrder,
)
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    FieldEvidenceORM,
    GoodsReceiptORM,
    InvoiceLineORM,
    InvoiceORM,
    PurchaseOrderORM,
    TenantORM,
    TolerancePolicyORM,
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
                review_reason=getattr(ev, "review_reason", None),
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

    async def list_supplier_invoices(
        self, tenant_id: UUID | str, supplier_tax_id: str, exclude_statuses: tuple[str, ...]
    ) -> List[InvoiceAggregate]:
        """Business keys of a supplier's invoices, for duplicate detection."""
        rows = await self._session.execute(
            select(InvoiceORM).where(
                InvoiceORM.tenant_id == str(tenant_id),
                InvoiceORM.supplier_tax_id == supplier_tax_id,
                InvoiceORM.status.not_in(exclude_statuses),
            )
        )
        return [
            InvoiceAggregate(
                id=row.id,
                tenant_id=row.tenant_id,
                document_id=row.document_id,
                supplier_tax_id=row.supplier_tax_id,
                invoice_number=row.invoice_number,
                invoice_series=row.invoice_series,
            )
            for row in rows.scalars().all()
        ]

    async def load_aggregate(self, invoice: InvoiceORM) -> InvoiceAggregate:
        """Current persisted invoice state as a domain aggregate (for re-validation/matching)."""
        lines = (
            (
                await self._session.execute(
                    select(InvoiceLineORM)
                    .where(InvoiceLineORM.invoice_id == invoice.id)
                    .order_by(InvoiceLineORM.line_no)
                )
            )
            .scalars()
            .all()
        )
        return InvoiceAggregate(
            id=invoice.id,
            tenant_id=invoice.tenant_id,
            document_id=invoice.document_id,
            revision=invoice.revision,
            status=InvoiceStatus(invoice.status),
            supplier_tax_id=invoice.supplier_tax_id,
            supplier_name=invoice.supplier_name,
            buyer_tax_id=invoice.buyer_tax_id,
            buyer_name=invoice.buyer_name,
            invoice_number=invoice.invoice_number,
            invoice_series=invoice.invoice_series,
            issue_date=invoice.issue_date,
            currency=invoice.currency,
            subtotal=invoice.subtotal,
            discount_total=invoice.discount_total,
            tax_total=invoice.tax_total,
            amount_payable=invoice.amount_payable,
            rounding_adjustment=invoice.rounding_adjustment,
            lines=[
                InvoiceLine(
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
                    purchase_order_line_id=line.po_line_id,
                )
                for line in lines
            ],
            signature_status=VerificationStatus(invoice.signature_status),
            tax_authority_status=VerificationStatus(invoice.tax_authority_status),
        )

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


class PolicyRepository:
    """Resolves the tolerance/approval policy in force for a tenant and vendor."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_effective(
        self, tenant_id: UUID | str, vendor_tax_id: Optional[str], as_of: date
    ) -> TolerancePolicy:
        scope = [TolerancePolicyORM.vendor_tax_id.is_(None)]
        if vendor_tax_id:
            scope.append(TolerancePolicyORM.vendor_tax_id == vendor_tax_id)
        stmt = (
            select(TolerancePolicyORM)
            .where(
                TolerancePolicyORM.tenant_id == str(tenant_id),
                TolerancePolicyORM.effective_from <= as_of,
                or_(*scope),
            )
            # Vendor-scoped rules override tenant defaults; newest effective version wins.
            .order_by(
                TolerancePolicyORM.vendor_tax_id.is_(None),
                TolerancePolicyORM.effective_from.desc(),
                TolerancePolicyORM.version.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return TolerancePolicy(tenant_id=str(tenant_id))
        return TolerancePolicy(
            id=row.id,
            tenant_id=row.tenant_id,
            vendor_tax_id=row.vendor_tax_id,
            version=row.version,
            price_tolerance_pct=row.price_tolerance_pct,
            qty_tolerance_pct=row.qty_tolerance_pct,
            max_amount_delta=row.max_amount_delta,
            auto_approve_threshold=row.auto_approve_threshold,
            separation_of_duties_required=row.separation_of_duties_required,
            auto_approval_enabled=row.auto_approval_enabled,
            po_required=row.po_required,
            goods_receipt_required=row.goods_receipt_required,
            line_description_min_similarity=row.line_description_min_similarity,
            effective_from=row.effective_from,
        )


class PurchasingRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_purchase_orders_for_vendor(
        self, tenant_id: UUID | str, vendor_tax_id: str
    ) -> List[PurchaseOrder]:
        stmt = (
            select(PurchaseOrderORM)
            .options(selectinload(PurchaseOrderORM.lines))
            .where(
                PurchaseOrderORM.tenant_id == str(tenant_id),
                PurchaseOrderORM.vendor_tax_id == vendor_tax_id,
            )
            .order_by(PurchaseOrderORM.order_date, PurchaseOrderORM.po_number)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_purchase_order(row) for row in rows]

    async def list_goods_receipts(
        self, tenant_id: UUID | str, po_id: UUID | str
    ) -> List[GoodsReceipt]:
        stmt = (
            select(GoodsReceiptORM)
            .options(selectinload(GoodsReceiptORM.lines))
            .where(
                GoodsReceiptORM.tenant_id == str(tenant_id),
                GoodsReceiptORM.po_id == str(po_id),
            )
            .order_by(GoodsReceiptORM.receipt_date, GoodsReceiptORM.grn_number)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_goods_receipt(row) for row in rows]


def _to_purchase_order(row: PurchaseOrderORM) -> PurchaseOrder:
    return PurchaseOrder(
        id=row.id,
        tenant_id=row.tenant_id,
        vendor_tax_id=row.vendor_tax_id,
        vendor_name=row.vendor_name,
        po_number=row.po_number,
        order_date=row.order_date,
        currency=row.currency,
        subtotal=row.subtotal,
        lines=[
            POLine(
                id=line.id,
                po_id=line.po_id,
                line_no=line.line_no,
                sku=line.sku,
                description=line.description,
                unit=line.unit,
                ordered_qty=line.ordered_qty,
                unit_price=line.unit_price,
                line_total=line.line_total,
            )
            for line in sorted(row.lines, key=lambda item: item.line_no)
        ],
    )


def _to_goods_receipt(row: GoodsReceiptORM) -> GoodsReceipt:
    return GoodsReceipt(
        id=row.id,
        tenant_id=row.tenant_id,
        po_id=row.po_id,
        grn_number=row.grn_number,
        receipt_date=row.receipt_date,
        lines=[
            GRNLine(
                id=line.id,
                grn_id=line.grn_id,
                po_line_id=line.po_line_id,
                line_no=line.line_no,
                received_qty=line.received_qty,
                rejected_qty=line.rejected_qty,
            )
            for line in row.lines
        ],
    )
