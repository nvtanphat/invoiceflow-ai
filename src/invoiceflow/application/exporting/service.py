"""Accounting export: approved invoices handed to the ERP exactly once.

Posting an export moves each included invoice APPROVED -> EXPORTED in the same transaction,
so a later export cannot include it again (the posted-entry lock used by AP systems such as
Odoo to prevent double booking and double payment).
"""

import base64
from decimal import Decimal
import json
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.domain.invoices.models import InvoiceStatus
from invoiceflow.infrastructure.database.models import AuditLogORM, ExportBatchORM, InvoiceORM

_APPROVED = InvoiceStatus.APPROVED.value
_EXPORTED = InvoiceStatus.EXPORTED.value


def _approved_invoices(tenant_id: str):
    return (
        select(InvoiceORM)
        .where(InvoiceORM.tenant_id == tenant_id, InvoiceORM.status == _APPROVED)
        .order_by(InvoiceORM.issue_date, InvoiceORM.invoice_number, InvoiceORM.id)
    )


async def list_exportable(session: AsyncSession, tenant_id: str) -> list[InvoiceORM]:
    """Read-only view of invoices that the next posted export would contain."""
    return list((await session.execute(_approved_invoices(tenant_id))).scalars().all())


async def claim_for_export(session: AsyncSession, tenant_id: str) -> list[InvoiceORM]:
    """Atomically mark every currently approved invoice as exported and return them."""
    stmt = _approved_invoices(tenant_id)
    bind = session.bind
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    invoices = list((await session.execute(stmt)).scalars().all())
    if not invoices:
        return []
    ids = [inv.id for inv in invoices]
    await session.execute(
        update(InvoiceORM)
        .where(
            InvoiceORM.tenant_id == tenant_id,
            InvoiceORM.id.in_(ids),
            InvoiceORM.status == _APPROVED,
        )
        .values(status=_EXPORTED, revision=InvoiceORM.revision + 1)
        .execution_options(synchronize_session=False)
    )
    for invoice in invoices:
        await session.refresh(invoice)
    return [inv for inv in invoices if inv.status == _EXPORTED]


def record_export(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
    invoices: list[InvoiceORM],
    sha256: str,
    format_kind: str,
) -> None:
    session.add(
        AuditLogORM(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="INVOICES_EXPORTED",
            aggregate_type="export",
            aggregate_id=sha256[:36],
            details_json=json.dumps(
                {
                    "invoice_ids": [inv.id for inv in invoices],
                    "sha256": sha256,
                    "format": format_kind,
                }
            ),
        )
    )


async def save_export_batch(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
    invoices: list[InvoiceORM],
    sha256: str,
    format_kind: str,
    file_bytes: bytes,
) -> ExportBatchORM:
    total_amount = sum((inv.amount_payable for inv in invoices), Decimal("0.0000"))
    batch_num = f"EXP-{uuid.uuid4().hex[:8].upper()}"
    batch = ExportBatchORM(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        batch_number=batch_num,
        format=format_kind,
        sha256=sha256,
        invoice_count=len(invoices),
        total_amount=total_amount,
        invoice_ids_json=json.dumps([inv.id for inv in invoices]),
        content_base64=base64.b64encode(file_bytes).decode("ascii"),
        created_by=actor_id,
    )
    session.add(batch)
    await session.flush()
    return batch


async def get_export_batch(
    session: AsyncSession, tenant_id: str, batch_id: str
) -> ExportBatchORM | None:
    stmt = select(ExportBatchORM).where(
        ExportBatchORM.tenant_id == tenant_id,
        or_(ExportBatchORM.id == batch_id, ExportBatchORM.sha256 == batch_id),
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def list_export_batches(
    session: AsyncSession, tenant_id: str, limit: int = 50
) -> list[ExportBatchORM]:
    stmt = (
        select(ExportBatchORM)
        .where(ExportBatchORM.tenant_id == tenant_id)
        .order_by(ExportBatchORM.created_at.desc())
        .limit(limit)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())
