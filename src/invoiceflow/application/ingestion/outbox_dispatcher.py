import logging
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.infrastructure.database.models import OutboxEventORM
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(self, db_manager: DatabaseSessionManager):
        self._db_manager = db_manager

    async def dispatch_pending_events(self, limit: int = 50) -> int:
        """Polls and dispatches unpublished outbox events to Dramatiq."""
        from invoiceflow.workers.actors import process_document_job

        dispatched_count = 0
        async with self._db_manager.session() as session:
            stmt = (
                select(OutboxEventORM)
                .where(OutboxEventORM.is_published.is_(False))
                .order_by(OutboxEventORM.created_at.asc())
                .limit(limit)
            )
            res = await session.execute(stmt)
            events = res.scalars().all()

            for event in events:
                try:
                    if event.topic == "document.received":
                        # Send job to worker queue
                        process_document_job.send(event.aggregate_id)
                    event.is_published = True
                    dispatched_count += 1
                except Exception as exc:
                    logger.warning("Failed to publish outbox event %s: %s", event.id, exc)

            await session.commit()

        return dispatched_count
