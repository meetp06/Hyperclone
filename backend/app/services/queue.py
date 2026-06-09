"""Single Arq pool shared across the FastAPI app for enqueueing jobs."""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis

from app.worker.main import WorkerSettings

_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(WorkerSettings.redis_settings)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
