import json
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.application.ingestion.preflight import IngestionPreflight
from invoiceflow.infrastructure.database.models import (
    DocumentORM,
    IdempotencyKeyORM,
    OutboxEventORM,
    ProcessingJobORM,
)
from invoiceflow.infrastructure.database.repositories import DocumentRepository
from invoiceflow.infrastructure.storage.service import StoragePort


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StoragePort,
        preflight: IngestionPreflight,
    ):
        self._session = session
        self._storage = storage
        self._preflight = preflight
        self._doc_repo = DocumentRepository(session)

    async def ingest_document(
        self,
        tenant_id: str,
        filename: str,
        content: bytes,
        idempotency_key: Optional[str] = None,
    ) -> tuple[DocumentORM, ProcessingJobORM, bool]:
        """Returns (DocumentORM, ProcessingJobORM, is_idempotent_replay)."""
        if idempotency_key:
            from sqlalchemy import select
            stmt = select(IdempotencyKeyORM).where(
                IdempotencyKeyORM.tenant_id == tenant_id,
                IdempotencyKeyORM.operation == "upload_document",
                IdempotencyKeyORM.idempotency_key == idempotency_key,
            )
            res = await self._session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                cached_data = json.loads(existing.response_body_json)
                doc = await self._doc_repo.get_document(tenant_id, cached_data["document_id"])
                job_stmt = select(ProcessingJobORM).where(
                    ProcessingJobORM.id == cached_data["job_id"]
                )
                job_res = await self._session.execute(job_stmt)
                job = job_res.scalar_one()
                return doc, job, True

        meta = self._preflight.inspect_and_validate(filename, content)
        storage_uri = await self._storage.save(tenant_id, filename, content)

        doc = await self._doc_repo.create_document(
            tenant_id=tenant_id,
            filename=meta.filename,
            mime_type=meta.detected_mime,
            file_size_bytes=meta.file_size_bytes,
            sha256=meta.sha256,
            storage_uri=storage_uri,
            page_count=meta.page_count,
        )

        job = ProcessingJobORM(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            document_id=doc.id,
            status="QUEUED",
            stage="PREFLIGHT",
        )
        self._session.add(job)

        outbox = OutboxEventORM(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            topic="document.received",
            aggregate_id=job.id,
            payload_json=json.dumps({"document_id": doc.id, "job_id": job.id}),
            is_published=False,
        )
        self._session.add(outbox)

        if idempotency_key:
            idemp = IdempotencyKeyORM(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                operation="upload_document",
                idempotency_key=idempotency_key,
                response_status=202,
                response_body_json=json.dumps({"document_id": doc.id, "job_id": job.id}),
            )
            self._session.add(idemp)

        await self._session.flush()
        return doc, job, False
