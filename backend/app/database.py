"""Async SQLAlchemy engine and session factory."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_config

# ---------------------------------------------------------------------------
# Engine — created once at module-import time (lazy singleton via get_config)
# ---------------------------------------------------------------------------

engine: AsyncEngine = create_async_engine(
    get_config().database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for use as a FastAPI dependency.

    Callers are responsible for committing or rolling back transactions.
    The session is always closed in the ``finally`` block.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
