import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from invoiceflow.api.dependencies import set_global_dependencies
from invoiceflow.api.routers import auth, documents, exports, health, invoices, jobs, matching
from invoiceflow.config import Settings, get_settings
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.storage.service import LocalStorageService, StoragePort

logger = logging.getLogger(__name__)


async def _run_outbox_loop(db_manager: DatabaseSessionManager, stop_event: asyncio.Event) -> None:
    from invoiceflow.application.ingestion.outbox_dispatcher import OutboxDispatcher

    dispatcher = OutboxDispatcher(db_manager)
    while not stop_event.is_set():
        try:
            await dispatcher.dispatch_pending_events(limit=50)
        except Exception as e:
            logger.debug("Outbox loop tick: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
        except (asyncio.TimeoutError, TimeoutError):
            pass


def create_app(
    database_url: Optional[str] = None,
    db_manager: Optional[DatabaseSessionManager] = None,
    storage: Optional[StoragePort] = None,
) -> FastAPI:
    settings = get_settings()
    db_url = database_url or settings.DATABASE_URL
    manager = db_manager or DatabaseSessionManager(db_url)
    store = storage or LocalStorageService(settings.LOCAL_STORAGE_DIR)

    set_global_dependencies(manager, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: verify database connectivity or init tables in dev
        try:
            await manager.create_tables()
        except Exception:
            pass

        stop_event = asyncio.Event()
        outbox_task = asyncio.create_task(_run_outbox_loop(manager, stop_event))
        yield
        # Shutdown
        stop_event.set()
        try:
            await asyncio.wait_for(outbox_task, timeout=2.0)
        except Exception:
            outbox_task.cancel()
        await manager.close()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Accounts Payable Document Processing, Validation and 3-Way Matching",
        lifespan=lifespan,
    )

    # CORS configuration with explicit allowlist (avoid wildcard when credentials enabled)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS or ["http://localhost:3000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Location", "If-Match"],
    )

    # Register Routers
    app.include_router(health.router)
    app.include_router(auth.router, prefix=settings.API_V1_STR)
    app.include_router(documents.router, prefix=settings.API_V1_STR)
    app.include_router(jobs.router, prefix=settings.API_V1_STR)
    app.include_router(invoices.router, prefix=settings.API_V1_STR)
    app.include_router(matching.router, prefix=settings.API_V1_STR)
    app.include_router(exports.router, prefix=settings.API_V1_STR)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred. Please consult system logs.",
            },
        )

    return app


app = create_app()
