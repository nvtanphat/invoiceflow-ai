"""Regression tests for the EXTRACTION_VERIFIED -> MATCHING_CLEARED -> ACCOUNTING_APPROVED gates.

Root causes covered:
- the worker reconciled without loading PO/GRN, so every invoice was MISSING_PO;
- manual approval did not check invoice status, match evidence or unresolved critical fields;
- the tenant policy lookup ignored vendor scope and effective dates.
"""

from datetime import date, timedelta
from decimal import Decimal
import json
import shutil
import tempfile
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.application.review.service import ReviewService
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceLine
from invoiceflow.domain.purchasing.models import MatchStatus
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    FieldEvidenceORM,
    GoodsReceiptLineORM,
    GoodsReceiptORM,
    InvoiceLineORM,
    InvoiceORM,
    MatchResultORM,
    PurchaseOrderLineORM,
    PurchaseOrderORM,
    TenantORM,
    TolerancePolicyORM,
)
from invoiceflow.infrastructure.database.repositories import PolicyRepository
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

VENDOR_TAX_ID = "0100109106"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_manager():
    manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await manager.create_tables()
    yield manager
    await manager.close()


async def _seed_tenant(session) -> str:
    tenant = TenantORM(name="Tenant gates")
    session.add(tenant)
    await session.flush()
    return tenant.id


async def _seed_po(session, tenant_id: str, with_grn: bool = True, po_number: str = "PO-1"):
    po = PurchaseOrderORM(
        tenant_id=tenant_id,
        vendor_tax_id=VENDOR_TAX_ID,
        vendor_name="Cong Ty A",
        po_number=po_number,
        order_date=date(2026, 11, 1),
        subtotal=Decimal("5000000.0000"),
    )
    session.add(po)
    await session.flush()
    po_line = PurchaseOrderLineORM(
        po_id=po.id,
        line_no=1,
        description="Dich vu Cloud",
        ordered_qty=Decimal("1.0000"),
        unit_price=Decimal("5000000.0000"),
        line_total=Decimal("5000000.0000"),
    )
    session.add(po_line)
    await session.flush()
    if with_grn:
        grn = GoodsReceiptORM(
            tenant_id=tenant_id,
            po_id=po.id,
            grn_number=f"GRN-{po_number}",
            receipt_date=date(2026, 11, 3),
        )
        session.add(grn)
        await session.flush()
        session.add(
            GoodsReceiptLineORM(
                grn_id=grn.id,
                po_line_id=po_line.id,
                line_no=1,
                received_qty=Decimal("1.0000"),
            )
        )
        await session.flush()
    return po


def _invoice(tenant_id: str) -> InvoiceAggregate:
    return InvoiceAggregate(
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id=VENDOR_TAX_ID,
        supplier_name="Cong Ty A",
        invoice_number="0000099",
        issue_date=date(2026, 11, 8),
        subtotal=Decimal("5000000.0000"),
        tax_total=Decimal("500000.0000"),
        amount_payable=Decimal("5500000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Dich vu Cloud",
                qty=Decimal("1.0000"),
                unit_price=Decimal("5000000.0000"),
                line_amount=Decimal("5000000.0000"),
            )
        ],
    )


async def test_reconciliation_loads_purchase_order_and_receipts(db_manager):
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        await _seed_po(session, tenant_id)

        report = await ReconciliationService(session).reconcile_invoice(_invoice(tenant_id))

    assert report.status == MatchStatus.MATCHED_EXACT
    assert report.is_matched is True


async def test_reconciliation_flags_ambiguous_purchase_orders(db_manager):
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        await _seed_po(session, tenant_id, po_number="PO-1")
        await _seed_po(session, tenant_id, po_number="PO-2")

        report = await ReconciliationService(session).reconcile_invoice(_invoice(tenant_id))

    assert report.status == MatchStatus.EXCEPTION
    assert report.is_matched is False
    assert "AMBIGUOUS_PURCHASE_ORDER" in [i.code for i in report.issues]


async def test_reconciliation_requires_goods_receipt_unless_policy_allows_two_way(db_manager):
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        await _seed_po(session, tenant_id, with_grn=False)

        three_way = await ReconciliationService(session).reconcile_invoice(_invoice(tenant_id))
        session.add(
            TolerancePolicyORM(
                tenant_id=tenant_id,
                goods_receipt_required=False,
                effective_from=date(2026, 1, 1),
            )
        )
        await session.flush()
        two_way = await ReconciliationService(session).reconcile_invoice(_invoice(tenant_id))

    assert three_way.status == MatchStatus.MISSING_GRN
    assert two_way.status == MatchStatus.MATCHED_EXACT


async def test_policy_repository_prefers_vendor_specific_effective_policy(db_manager):
    today = date(2026, 11, 10)
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        session.add_all(
            [
                TolerancePolicyORM(
                    tenant_id=tenant_id,
                    auto_approval_enabled=False,
                    effective_from=date(2026, 1, 1),
                ),
                TolerancePolicyORM(
                    tenant_id=tenant_id,
                    vendor_tax_id=VENDOR_TAX_ID,
                    auto_approval_enabled=True,
                    effective_from=date(2026, 6, 1),
                ),
                TolerancePolicyORM(
                    tenant_id=tenant_id,
                    vendor_tax_id=VENDOR_TAX_ID,
                    auto_approval_enabled=False,
                    effective_from=today + timedelta(days=30),
                ),
            ]
        )
        await session.flush()
        repo = PolicyRepository(session)

        vendor_policy = await repo.get_effective(tenant_id, VENDOR_TAX_ID, today)
        other_policy = await repo.get_effective(tenant_id, "0309998887", today)
        missing_policy = await repo.get_effective(str(uuid.uuid4()), VENDOR_TAX_ID, today)

    assert vendor_policy.auto_approval_enabled is True
    assert other_policy.auto_approval_enabled is False
    assert missing_policy.auto_approval_enabled is False
    assert missing_policy.separation_of_duties_required is True


async def _seed_reviewable_invoice(session, tenant_id: str, status: str = "READY_FOR_REVIEW"):
    invoice = InvoiceORM(
        tenant_id=tenant_id,
        document_id=str(uuid.uuid4()),
        revision=1,
        status=status,
        supplier_tax_id=VENDOR_TAX_ID,
        supplier_name="Cong Ty A",
        invoice_number="0000099",
        currency="VND",
        subtotal=Decimal("5000000.0000"),
        discount_total=Decimal("0.0000"),
        tax_total=Decimal("500000.0000"),
        amount_payable=Decimal("5500000.0000"),
        rounding_adjustment=Decimal("0.0000"),
    )
    session.add(invoice)
    await session.flush()
    session.add(
        InvoiceLineORM(
            invoice_id=invoice.id,
            line_no=1,
            description="Dich vu Cloud",
            qty=Decimal("1.0000"),
            unit_price=Decimal("5000000.0000"),
            discount=Decimal("0.0000"),
            line_amount=Decimal("5000000.0000"),
        )
    )
    await session.flush()
    return invoice


def _cleared_match(tenant_id: str, invoice_id: str) -> MatchResultORM:
    return MatchResultORM(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        status=MatchStatus.MATCHED_EXACT.value,
        is_matched=True,
        requires_review=False,
        issues_json="[]",
    )


@pytest.mark.parametrize("status", ["REJECTED", "APPROVED", "EXPORTED"])
async def test_manual_approval_rejects_non_reviewable_status(db_manager, status):
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        invoice = await _seed_reviewable_invoice(session, tenant_id, status=status)
        session.add(_cleared_match(tenant_id, invoice.id))
        await session.flush()

        with pytest.raises(ValueError, match="INVOICE_NOT_REVIEWABLE"):
            await ReviewService(session).approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                expected_revision=1,
                actor_id="approver",
                notes="approve",
            )


async def test_manual_approval_requires_a_match_result(db_manager):
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        invoice = await _seed_reviewable_invoice(session, tenant_id)

        with pytest.raises(ValueError, match="MATCH_REPORT_REQUIRED"):
            await ReviewService(session).approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                expected_revision=1,
                actor_id="approver",
                notes="approve",
            )


async def test_manual_approval_blocks_unresolved_critical_evidence_until_field_is_corrected(
    db_manager,
):
    async with db_manager.session() as session:
        tenant_id = await _seed_tenant(session)
        invoice = await _seed_reviewable_invoice(session, tenant_id)
        session.add(_cleared_match(tenant_id, invoice.id))
        session.add(
            FieldEvidenceORM(
                invoice_id=invoice.id,
                field_path="invoice_number",
                source_kind="docling_table",
                raw_value="0000O99",
                normalized_value="0000O99",
                extractor="docling",
                verification_state="invalid",
            )
        )
        await session.flush()
        review = ReviewService(session)

        with pytest.raises(ValueError, match="UNRESOLVED_CRITICAL_FIELD"):
            await review.approve_invoice(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                expected_revision=1,
                actor_id="approver",
                notes="approve",
            )

        await review.update_invoice_fields(
            tenant_id=tenant_id,
            invoice_id=invoice.id,
            expected_revision=1,
            actor_id="reviewer",
            patches={"invoice_number": "0000099"},
            reason="Checked against original document",
        )
        evidence = (
            await session.execute(
                select(FieldEvidenceORM).where(
                    FieldEvidenceORM.invoice_id == invoice.id,
                    FieldEvidenceORM.field_path == "invoice_number",
                )
            )
        ).scalar_one()
        assert evidence.verification_state == "human_approved"
        assert evidence.normalized_value == "0000099"

        approved = await review.approve_invoice(
            tenant_id=tenant_id,
            invoice_id=invoice.id,
            expected_revision=2,
            actor_id="approver",
            notes="Approved after correction; non-PO invoice accepted by accountant",
        )
        assert approved.status == "APPROVED"


XML_INVOICE = b"""<?xml version="1.0" encoding="UTF-8"?>
<HDon><DLHDon>
  <TTChung><KHHDon>1C26TAA</KHHDon><SHDon>0000099</SHDon><NLap>2026-11-08</NLap><DVTTe>VND</DVTTe></TTChung>
  <NDHDon>
    <NBan><Ten>Cong Ty A</Ten><MST>0100109106</MST></NBan>
    <NMua><Ten>Cong Ty B</Ten><MST>0309998887</MST></NMua>
    <DSHHDVu><HHDVu><STT>1</STT><THHDVu>Dich vu Cloud</THHDVu><SLuong>1</SLuong>
      <DGia>5000000</DGia><ThTien>5000000</ThTien></HHDVu></DSHHDVu>
    <TToan><TgTCThue>5000000</TgTCThue><TgTThue>500000</TgTThue><TgTTTBSo>5500000</TgTTTBSo></TToan>
  </NDHDon>
</DLHDon></HDon>"""


async def _run_xml_job(db_manager, auto_approval_enabled: bool):
    from invoiceflow.application.ingestion.preflight import IngestionPreflight
    from invoiceflow.application.ingestion.service import IngestionService
    from invoiceflow.application.processing.coordinator import JobCoordinator
    from invoiceflow.infrastructure.storage.service import LocalStorageService

    tmp_dir = tempfile.mkdtemp()
    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        async with db_manager.session() as session:
            tenant_id = await _seed_tenant(session)
            await _seed_po(session, tenant_id)
            session.add(
                TolerancePolicyORM(
                    tenant_id=tenant_id,
                    auto_approval_enabled=auto_approval_enabled,
                    effective_from=date(2026, 1, 1),
                )
            )
            ingestion = IngestionService(session, storage, IngestionPreflight())
            _, job, _ = await ingestion.ingest_document(
                tenant_id=tenant_id, filename="invoice.xml", content=XML_INVOICE
            )
            job_id = job.id

        assert await JobCoordinator(db_manager=db_manager, storage=storage).process_job(job_id)

        async with db_manager.session() as session:
            invoice = (
                await session.execute(select(InvoiceORM).where(InvoiceORM.tenant_id == tenant_id))
            ).scalar_one()
            audits = (
                (
                    await session.execute(
                        select(AuditLogORM).where(AuditLogORM.aggregate_id == invoice.id)
                    )
                )
                .scalars()
                .all()
            )
        return invoice, {audit.action: json.loads(audit.details_json) for audit in audits}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def test_worker_auto_approves_only_when_all_gates_and_policy_pass(db_manager):
    invoice, audits = await _run_xml_job(db_manager, auto_approval_enabled=True)

    assert invoice.status == "APPROVED"
    gates = audits["AUTO_APPROVED_STP"]["gates"]
    assert gates == {
        "extraction_verified": True,
        "matching_cleared": True,
        "accounting_approved": True,
    }


async def test_worker_routes_cleared_invoice_to_review_when_auto_approval_disabled(db_manager):
    invoice, audits = await _run_xml_job(db_manager, auto_approval_enabled=False)

    assert invoice.status == "READY_FOR_REVIEW"
    details = audits["ROUTED_TO_HUMAN_REVIEW"]
    assert details["gates"] == {
        "extraction_verified": True,
        "matching_cleared": True,
        "accounting_approved": False,
    }
    assert "AUTO_APPROVAL_DISABLED_BY_POLICY" in details["review_reasons"]
