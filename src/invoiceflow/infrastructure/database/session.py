from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from invoiceflow.infrastructure.database.base import Base


class DatabaseSessionManager:
    def __init__(self, database_url: str, echo: bool = False):
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            echo=echo,
            future=True,
        )
        self._sessionmaker = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def create_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if "sqlite" in str(self._engine.url):
                from sqlalchemy import text

                res = await conn.execute(text("PRAGMA table_info(documents)"))
                cols = [row[1] for row in res.fetchall()]
                if cols and "uploaded_by" not in cols:
                    await conn.execute(
                        text("ALTER TABLE documents ADD COLUMN uploaded_by VARCHAR(64)")
                    )

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
