from typing import Optional
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import (
    AuthenticatedContext,
    get_current_context,
    get_db,
    get_storage,
    require_role,
)
from invoiceflow.application.ingestion.preflight import IngestionPreflight, PreflightError
from invoiceflow.application.ingestion.service import IngestionService
from invoiceflow.infrastructure.database.models import DocumentORM
from invoiceflow.infrastructure.database.repositories import DocumentRepository
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.document.page_orientation import normalize_page_rotation
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.storage.service import StoragePort

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage),
):
    preflight = IngestionPreflight()
    ingestion = IngestionService(session, storage, preflight)

    content = await file.read()
    try:
        doc, job, is_replay = await ingestion.ingest_document(
            tenant_id=ctx.tenant_id,
            filename=file.filename or "upload.bin",
            content=content,
            idempotency_key=idempotency_key,
            uploaded_by=ctx.user_id,
        )
        await session.commit()
    except PreflightError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception:
        await session.rollback()
        raise

    if not is_replay:
        try:
            from invoiceflow.workers.actors import process_document_job

            process_document_job.send(job.id)
        except Exception:
            pass

    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    created_at_str = doc.created_at.isoformat() if getattr(doc, "created_at", None) else ""
    return {
        "document_id": doc.id,
        "job_id": job.id,
        "status": job.status,
        "sha256": doc.sha256,
        "is_idempotent_replay": is_replay,
        "status_url": f"/api/v1/jobs/{job.id}",
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "mime_type": doc.mime_type,
            "file_size_bytes": doc.file_size_bytes,
            "status": doc.status,
            "created_at": created_at_str,
        },
        "job": {
            "id": job.id,
            "document_id": job.document_id,
            "status": job.status,
            "stage": job.stage,
        },
    }


@router.get("")
async def list_documents(
    limit: int = 50,
    offset: int = 0,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    stmt = (
        select(DocumentORM)
        .where(DocumentORM.tenant_id == ctx.tenant_id)
        .order_by(DocumentORM.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await session.execute(stmt)
    docs = res.scalars().all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "mime_type": d.mime_type,
            "file_size_bytes": d.file_size_bytes,
            "sha256": d.sha256,
            "status": d.status,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    doc_repo = DocumentRepository(session)
    doc = await doc_repo.get_document(ctx.tenant_id, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return {
        "id": doc.id,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "file_size_bytes": doc.file_size_bytes,
        "sha256": doc.sha256,
        "status": doc.status,
        "page_count": doc.page_count,
        "created_at": doc.created_at.isoformat(),
    }


@router.get("/{document_id}/preview")
async def preview_document(
    document_id: str,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage),
):
    doc_repo = DocumentRepository(session)
    doc = await doc_repo.get_document(ctx.tenant_id, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    try:
        content = await storage.get(doc.storage_uri)
    except (FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found in storage.",
        )
    return Response(content=content, media_type=doc.mime_type)


@router.get("/{document_id}/pages/{page_index}/render")
async def render_document_page(
    document_id: str,
    page_index: int = 0,
    dpi: int = Query(150, ge=36, le=300),
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(get_storage),
):
    doc_repo = DocumentRepository(session)
    doc = await doc_repo.get_document(ctx.tenant_id, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    try:
        content = await storage.get(doc.storage_uri)
    except (FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found in storage.",
        )
    if doc.mime_type == "application/pdf" or doc.filename.lower().endswith(".pdf"):
        import fitz

        # Render exactly the page OCR ran on, so evidence coordinates line up with the image.
        page_classes = PDFInspector().inspect(content).page_classifications
        content = normalize_page_rotation(content, get_settings().OCR_DPI, page_classes)
        doc_pdf = fitz.open(stream=content, filetype="pdf")
        if page_index < 0 or page_index >= len(doc_pdf):
            doc_pdf.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Page index {page_index} out of range (total pages: {len(doc_pdf)}).",
            )
        page = doc_pdf.load_page(page_index)
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        page_count = len(doc_pdf)
        # get_pixmap applies any remaining /Rotate, so the served image is already upright.
        rotation = 0
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        doc_pdf.close()
        response = Response(content=png_bytes, media_type="image/png")
        response.headers["X-Page-Width"] = str(page_width)
        response.headers["X-Page-Height"] = str(page_height)
        response.headers["X-Page-Count"] = str(page_count)
        response.headers["X-Page-Rotation"] = str(rotation)
        response.headers["Access-Control-Expose-Headers"] = (
            "X-Page-Width, X-Page-Height, X-Page-Count, X-Page-Rotation"
        )
        return response
    elif doc.mime_type.startswith("image/"):
        import fitz

        pix = fitz.Pixmap(content)
        w, h = float(pix.width), float(pix.height)
        response = Response(content=content, media_type=doc.mime_type)
        response.headers["X-Page-Width"] = str(w)
        response.headers["X-Page-Height"] = str(h)
        response.headers["X-Page-Count"] = "1"
        response.headers["X-Page-Rotation"] = "0"
        response.headers["Access-Control-Expose-Headers"] = (
            "X-Page-Width, X-Page-Height, X-Page-Count, X-Page-Rotation"
        )
        return response
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document format does not support page image rendering.",
        )
