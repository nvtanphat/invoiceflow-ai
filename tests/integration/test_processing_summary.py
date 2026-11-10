"""Dashboard metrics come from recorded pipeline decisions, never from generated series."""

from datetime import date, datetime, time, timedelta, timezone
import uuid

import pytest
import pytest_asyncio

from invoiceflow.application.reporting.processing_summary import processing_summary
from invoiceflow.infrastructure.database.models import AuditLogORM, DocumentORM, TenantORM
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

pytestmark = pytest.mark.asyncio
TODAY = date(2026, 11, 10)


@pytest_asyncio.fixture
async def db_manager():
    manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await manager.create_tables()
    yield manager
    await manager.close()


def _at(day: date) -> datetime:
    return datetime.combine(day, time(10, 0), tzinfo=timezone.utc)


def _audit(tenant_id: str, action: str, day: date) -> AuditLogORM:
    return AuditLogORM(
        tenant_id=tenant_id,
        action=action,
        aggregate_type="INVOICE",
        aggregate_id=str(uuid.uuid4()),
        created_at=_at(day),
    )


def _document(tenant_id: str, day: date) -> DocumentORM:
    return DocumentORM(
        tenant_id=tenant_id,
        filename="a.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        sha256=uuid.uuid4().hex,
        storage_uri="local://a",
        created_at=_at(day),
        updated_at=_at(day),
    )


async def test_summary_buckets_recorded_decisions_per_day_and_isolates_tenants(db_manager):
    yesterday = TODAY - timedelta(days=1)
    async with db_manager.session() as session:
        tenant = TenantORM(name="A")
        other = TenantORM(name="B")
        session.add_all([tenant, other])
        await session.flush()
        session.add_all(
            [
                _document(tenant.id, yesterday),
                _document(tenant.id, TODAY),
                _document(tenant.id, TODAY),
                _audit(tenant.id, "AUTO_APPROVED_STP", TODAY),
                _audit(tenant.id, "ROUTED_TO_HUMAN_REVIEW", TODAY),
                _audit(tenant.id, "ROUTED_TO_HUMAN_REVIEW", yesterday),
                _audit(tenant.id, "INVOICE_APPROVE", TODAY),
                _audit(tenant.id, "INVOICE_REJECT", yesterday),
                _audit(tenant.id, "AUTO_APPROVED_STP", TODAY - timedelta(days=3)),
                _audit(other.id, "AUTO_APPROVED_STP", TODAY),
                _document(other.id, TODAY),
            ]
        )
        await session.flush()

        summary = await processing_summary(session, tenant.id, days=2, today=TODAY)

    assert [d["date"] for d in summary["days"]] == [yesterday.isoformat(), TODAY.isoformat()]
    assert summary["days"][1] == {
        "date": TODAY.isoformat(),
        "received": 2,
        "auto_approved": 1,
        "routed_to_review": 1,
        "manual_approved": 1,
        "rejected": 0,
    }
    assert summary["totals"]["received"] == 3
    assert summary["totals"]["routed_to_review"] == 2
    # STP rate = system approvals / invoices the pipeline decided on in the window.
    assert summary["stp_rate"] == pytest.approx(1 / 3)
    # The previous window of equal length holds the older auto approval.
    assert summary["previous_totals"]["auto_approved"] == 1
    assert summary["previous_stp_rate"] == pytest.approx(1.0)


async def test_summary_reports_unknown_rates_instead_of_inventing_them(db_manager):
    async with db_manager.session() as session:
        tenant = TenantORM(name="Empty")
        session.add(tenant)
        await session.flush()

        summary = await processing_summary(session, tenant.id, days=7, today=TODAY)

    assert len(summary["days"]) == 7
    assert summary["totals"]["received"] == 0
    assert summary["stp_rate"] is None
    assert summary["previous_stp_rate"] is None


async def test_summary_endpoint_requires_auth_and_scopes_to_tenant(db_manager):
    from httpx import ASGITransport, AsyncClient

    from invoiceflow.api.dependencies import create_access_token
    from invoiceflow.api.main import create_app
    from invoiceflow.config import get_settings
    from invoiceflow.infrastructure.database.models import MembershipORM, UserORM

    async with db_manager.session() as session:
        tenant = TenantORM(name="Api")
        user = UserORM(email="viewer@sum.vn", hashed_password="x", full_name="Viewer")
        session.add_all([tenant, user])
        await session.flush()
        session.add(MembershipORM(tenant_id=tenant.id, user_id=user.id, role="viewer"))
        session.add(_audit(tenant.id, "AUTO_APPROVED_STP", datetime.now(timezone.utc).date()))
        tenant_id, user_id = tenant.id, user.id

    app = create_app(database_url="sqlite+aiosqlite:///:memory:", db_manager=db_manager)
    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="viewer",
        email="viewer@sum.vn",
        settings=get_settings(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = "/api/v1/reports/processing-summary?days=7"
        assert (await client.get(url)).status_code == 401
        res = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["totals"]["auto_approved"] == 1
        assert (
            await client.get(
                "/api/v1/reports/processing-summary?days=500",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).status_code == 422
