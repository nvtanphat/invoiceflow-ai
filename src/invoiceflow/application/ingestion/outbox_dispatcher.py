import logging
from sqlalchemy import select
from invoiceflow.infrastructure.database.models import OutboxEventORM
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(self, db_manager: DatabaseSessionManager):
        self._db_manager = db_manager

    async def dispatch_pending_events(self, limit: int = 50) -> int:
        """Polls and dispatches unpublished outbox events to Dramatiq with concurrency protection."""
        from invoiceflow.workers.actors import process_document_job

        dispatched_count = 0
        async with self._db_manager.session() as session:
            stmt = (
                select(OutboxEventORM)
                .where(OutboxEventORM.is_published.is_(False))
                .order_by(OutboxEventORM.created_at.asc())
                .limit(limit)
            )

            # Concurrent dispatcher protection: lock rows on PostgreSQL to prevent double-dispatch
            bind = session.bind
            if bind and bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)

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
                    logger.warning("Failed to publish outbox event %s to broker: %s", event.id, exc)

            await session.commit()

        return dispatched_count
