"""Direct TimescaleDB writes for check results."""

from datetime import datetime, timezone
from uuid import uuid4

import asyncpg

from worker.config import worker_settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=worker_settings.asyncpg_dsn,
            min_size=2,
            max_size=10,
        )
    return _pool


async def validate_monitor_exists(monitor_id: str, tenant_id: str | None = None) -> bool:
    """Verify that the monitor exists in the database and is active.
    
    This prevents processing of forged or injected jobs that reference
    non-existent or inactive monitors.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if tenant_id:
            row = await conn.fetchrow(
                "SELECT status FROM monitors WHERE id = $1 AND tenant_id = $2",
                monitor_id, tenant_id
            )
        else:
            row = await conn.fetchrow(
                "SELECT status FROM monitors WHERE id = $1",
                monitor_id
            )
        
        if not row:
            return False
        
        # Only process active monitors
        return row["status"] == "active"


async def write_check_result(
    monitor_id: str,
    status: str,
    response_time_ms: float | None = None,
    status_code: int | None = None,
    error: str | None = None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO check_results (id, monitor_id, checked_at, status, response_time_ms, status_code, error)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            str(uuid4()), monitor_id, datetime.now(timezone.utc),
            status, response_time_ms, status_code, error,
        )


async def get_consecutive_failures(monitor_id: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status FROM check_results WHERE monitor_id = $1 ORDER BY checked_at DESC LIMIT 100",
            monitor_id,
        )
    count = 0
    for r in rows:
        if r["status"] != "up":
            count += 1
        else:
            break
    return count


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
