"""Daily processing metrics derived from recorded pipeline decisions (audit log) and uploads.

Days are UTC calendar days; presentation layers convert to local time if needed.
"""

from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.infrastructure.database.models import AuditLogORM, DocumentORM

_ACTION_METRICS = {
    "AUTO_APPROVED_STP": "auto_approved",
    "ROUTED_TO_HUMAN_REVIEW": "routed_to_review",
    "INVOICE_APPROVE": "manual_approved",
    "INVOICE_REJECT": "rejected",
}
_METRICS = ("received", *_ACTION_METRICS.values())


async def processing_summary(
    session: AsyncSession, tenant_id: str, days: int, today: date
) -> dict[str, Any]:
    start = today - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    counts = await _daily_counts(session, tenant_id, previous_start, today)

    window = [start + timedelta(days=offset) for offset in range(days)]
    previous = [previous_start + timedelta(days=offset) for offset in range(days)]
    daily = [{"date": day.isoformat(), **counts.get(day, _empty())} for day in window]
    totals = _sum(counts.get(day, _empty()) for day in window)
    previous_totals = _sum(counts.get(day, _empty()) for day in previous)
    return {
        "window_days": days,
        "days": daily,
        "totals": totals,
        "previous_totals": previous_totals,
        "stp_rate": _stp_rate(totals),
        "previous_stp_rate": _stp_rate(previous_totals),
    }


async def _daily_counts(
    session: AsyncSession, tenant_id: str, first: date, last: date
) -> dict[date, dict[str, int]]:
    counts: dict[date, dict[str, int]] = {}
    audit_day = func.date(AuditLogORM.created_at)
    audit_rows = await session.execute(
        select(audit_day, AuditLogORM.action, func.count())
        .where(
            AuditLogORM.tenant_id == tenant_id,
            AuditLogORM.action.in_(_ACTION_METRICS),
            audit_day >= first.isoformat(),
            audit_day <= last.isoformat(),
        )
        .group_by(audit_day, AuditLogORM.action)
    )
    for day, action, count in audit_rows.all():
        counts.setdefault(_as_date(day), _empty())[_ACTION_METRICS[action]] += count

    upload_day = func.date(DocumentORM.created_at)
    upload_rows = await session.execute(
        select(upload_day, func.count())
        .where(
            DocumentORM.tenant_id == tenant_id,
            upload_day >= first.isoformat(),
            upload_day <= last.isoformat(),
        )
        .group_by(upload_day)
    )
    for day, count in upload_rows.all():
        counts.setdefault(_as_date(day), _empty())["received"] += count
    return counts


def _as_date(value: Any) -> date:
    # SQLite returns ISO text for date(), PostgreSQL a date object.
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _empty() -> dict[str, int]:
    return {metric: 0 for metric in _METRICS}


def _sum(rows: Any) -> dict[str, int]:
    total = _empty()
    for row in rows:
        for metric in _METRICS:
            total[metric] += row[metric]
    return total


def _stp_rate(totals: dict[str, int]) -> Optional[float]:
    decided = totals["auto_approved"] + totals["routed_to_review"]
    return totals["auto_approved"] / decided if decided else None
