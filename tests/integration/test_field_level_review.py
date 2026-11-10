"""Field-level review: a reviewer resolves one flagged field at a time against the source."""

from decimal import Decimal
import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from invoiceflow.application.review.service import ConcurrencyConflictError, ReviewService
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    FieldEvidenceORM,
    InvoiceLineORM,
    InvoiceORM,
    MembershipORM,
    TenantORM,
    UserORM,
)
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_manager():
    manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await manager.create_tables()
    yield manager
    await manager.close()


async def _seed(session) -> tuple[str, str]:
    tenant = TenantORM(name="Review tenant")
    session.add(tenant)
    await session.flush()
    invoice = InvoiceORM(
        tenant_id=tenant.id,
        document_id=str(uuid.uuid4()),
        revision=1,
        status="READY_FOR_REVIEW",
        supplier_tax_id="0100109106",
        invoice_number="0005599",
        currency="VND",
        subtotal=Decimal("6000000.0000"),
        discount_total=Decimal("0.0000"),
        tax_total=Decimal("6000000.0000"),
        amount_payable=Decimal("66000000.0000"),
        rounding_adjustment=Decimal("0.0000"),
    )
    session.add(invoice)
    await session.flush()
    session.add_all(
        [
            InvoiceLineORM(
                invoice_id=invoice.id,
                line_no=1,
                description="Laptop",
                qty=Decimal("2.0000"),
                unit_price=Decimal("30000000.0000"),
                discount=Decimal("0.0000"),
                line_amount=Decimal("60000000.0000"),
            ),
            FieldEvidenceORM(
                invoice_id=invoice.id,
                field_path="subtotal",
                source_kind="pdf",
                raw_value="Cong tien hang: 6ooo0000",
                normalized_value="6000000.0000",
                extractor="docling",
                verification_state="conflict",
            ),
            FieldEvidenceORM(
                invoice_id=invoice.id,
                field_path="subtotal.candidate_vision",
                source_kind="vision_llm",
                normalized_value="60000000.0000",
                extractor="openai_vision",
                verification_state="model_proposed",
            ),
            FieldEvidenceORM(
                invoice_id=invoice.id,
                field_path="invoice_number",
                source_kind="pdf",
                raw_value="So: 0005599",
                normalized_value="0005599",
                extractor="docling",
                verification_state="uncertain",
            ),
            FieldEvidenceORM(
                invoice_id=invoice.id,
                field_path="invoice_number.candidate_vision",
                source_kind="vision_llm",
                normalized_value="0005569",
                extractor="openai_vision",
                verification_state="model_proposed",
            ),
        ]
    )
    await session.flush()
    return tenant.id, invoice.id


async def _states(session, invoice_id: str) -> dict[str, str]:
    rows = (
        (
            await session.execute(
                select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    return {row.field_path: row.verification_state for row in rows}


async def test_accept_candidate_applies_the_vision_value_to_that_field_only(db_manager):
    async with db_manager.session() as session:
        tenant_id, invoice_id = await _seed(session)

        invoice = await ReviewService(session).resolve_field(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            expected_revision=1,
            actor_id="reviewer",
            field_path="subtotal",
            decision="accept_candidate",
        )

        assert invoice.subtotal == Decimal("60000000.0000")
        assert invoice.revision == 2
        states = await _states(session, invoice_id)
        assert states["subtotal"] == "human_approved"
        assert states["subtotal.candidate_vision"] == "human_approved"
        assert states["invoice_number.candidate_vision"] == "model_proposed"


async def test_accept_extracted_keeps_value_and_rejects_the_competing_candidate(db_manager):
    async with db_manager.session() as session:
        tenant_id, invoice_id = await _seed(session)

        invoice = await ReviewService(session).resolve_field(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            expected_revision=1,
            actor_id="reviewer",
            field_path="invoice_number",
            decision="accept_extracted",
        )

        assert invoice.invoice_number == "0005599"
        assert invoice.revision == 2
        states = await _states(session, invoice_id)
        assert states["invoice_number"] == "human_approved"
        assert states["invoice_number.candidate_vision"] == "human_rejected"
        audit = (
            (
                await session.execute(
                    select(AuditLogORM).where(AuditLogORM.aggregate_id == invoice_id)
                )
            )
            .scalars()
            .all()
        )
        confirmed = [a for a in audit if a.action == "INVOICE_FIELD_CONFIRMED"]
        assert json.loads(confirmed[0].details_json)["field_path"] == "invoice_number"


async def test_correct_with_own_value_rejects_a_different_candidate(db_manager):
    async with db_manager.session() as session:
        tenant_id, invoice_id = await _seed(session)

        invoice = await ReviewService(session).resolve_field(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            expected_revision=1,
            actor_id="reviewer",
            field_path="subtotal",
            decision="correct",
            value="60000000",
        )

        assert invoice.subtotal == Decimal("60000000")
        states = await _states(session, invoice_id)
        assert states["subtotal"] == "human_approved"
        # The reviewer's value equals the candidate, so the candidate was right.
        assert states["subtotal.candidate_vision"] == "human_approved"


async def test_resolve_field_rejects_unknown_fields_missing_candidates_and_stale_revisions(
    db_manager,
):
    async with db_manager.session() as session:
        tenant_id, invoice_id = await _seed(session)
        review = ReviewService(session)

        with pytest.raises(ValueError, match="FIELD_NOT_REVIEWABLE"):
            await review.resolve_field(tenant_id, invoice_id, 1, "r", "status", "accept_extracted")
        with pytest.raises(ValueError, match="NO_CANDIDATE"):
            await review.resolve_field(
                tenant_id, invoice_id, 1, "r", "tax_total", "accept_candidate"
            )
        with pytest.raises(ValueError, match="VALUE_REQUIRED"):
            await review.resolve_field(tenant_id, invoice_id, 1, "r", "subtotal", "correct")
        with pytest.raises(ConcurrencyConflictError):
            await review.resolve_field(
                tenant_id, invoice_id, 7, "r", "invoice_number", "accept_extracted"
            )


async def test_review_api_exposes_review_items_and_resolves_a_field(db_manager):
    from invoiceflow.api.dependencies import create_access_token
    from invoiceflow.api.main import create_app
    from invoiceflow.config import get_settings

    async with db_manager.session() as session:
        tenant_id, invoice_id = await _seed(session)
        user = UserORM(email="rv@field.vn", hashed_password="x", full_name="Reviewer")
        session.add(user)
        await session.flush()
        session.add(MembershipORM(tenant_id=tenant_id, user_id=user.id, role="reviewer"))
        user_id = user.id

    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="reviewer",
        email="rv@field.vn",
        settings=get_settings(),
    )
    app = create_app(database_url="sqlite+aiosqlite:///:memory:", db_manager=db_manager)
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        detail = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=headers)).json()
        items = {item["field_path"]: item for item in detail["review_items"]}
        assert items["subtotal"]["candidate_value"] == "60000000.0000"

        res = await client.post(
            f"/api/v1/invoices/{invoice_id}/review",
            headers={**headers, "If-Match": '"1"'},
            json={
                "action": "resolve_field",
                "field_path": "subtotal",
                "decision": "accept_candidate",
            },
        )
        assert res.status_code == 200
        assert res.json()["revision"] == 2

        detail = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=headers)).json()
        assert "subtotal" not in {item["field_path"] for item in detail["review_items"]}
