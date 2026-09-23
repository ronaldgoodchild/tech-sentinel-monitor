"""Database connection pool using asyncpg and Redis client."""

from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis

from app.config import settings

_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_dsn,
            min_size=2,
            max_size=10,
        )
    return _pool


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


@asynccontextmanager
async def get_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def close_connections():
    global _pool, _redis
    if _pool:
        await _pool.close()
        _pool = None
    if _redis:
        await _redis.close()
        _redis = None
