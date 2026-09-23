"""Database model helpers — SQL queries for CRUD operations."""

from datetime import datetime, timezone
from uuid import uuid4

from app.database import get_db


def _now():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid4())


# ── Tenants ──────────────────────────────────────────────────────────────────

async def create_tenant(name: str, slug: str, api_key: str | None = None):
    tenant_id = _uuid()
    api_key = api_key or _uuid()
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tenants (id, name, slug, api_key, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $5)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, updated_at = $5
            RETURNING *
            """,
            tenant_id, name, slug, api_key, _now(),
        )
    return dict(row)


async def get_tenant(tenant_id: str):
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM tenants WHERE id = $1", tenant_id)
    return dict(row) if row else None


async def get_tenant_by_slug(slug: str):
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM tenants WHERE slug = $1", slug)
    return dict(row) if row else None


async def get_tenant_by_api_key(api_key: str):
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM tenants WHERE api_key = $1", api_key)
    return dict(row) if row else None


async def list_tenants():
    async with get_db() as conn:
        rows = await conn.fetch("SELECT * FROM tenants ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def delete_tenant(tenant_id: str):
    async with get_db() as conn:
        await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)


# ── Monitors ─────────────────────────────────────────────────────────────────

async def create_monitor(
    tenant_id: str,
    name: str,
    monitor_type: str,
    target: str,
    interval_seconds: int = 60,
    timeout_seconds: int = 10,
    external_id: str | None = None,
    config: dict | None = None,
):
    import json
    monitor_id = _uuid()
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO monitors
                (id, tenant_id, name, monitor_type, target, interval_seconds,
                 timeout_seconds, external_id, config, status, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'active',$10,$10)
            ON CONFLICT (tenant_id, external_id)
                DO UPDATE SET name=EXCLUDED.name, monitor_type=EXCLUDED.monitor_type,
                    target=EXCLUDED.target, interval_seconds=EXCLUDED.interval_seconds,
                    timeout_seconds=EXCLUDED.timeout_seconds, config=EXCLUDED.config,
                    updated_at=EXCLUDED.updated_at
            RETURNING *
            """,
            monitor_id, tenant_id, name, monitor_type, target,
            interval_seconds, timeout_seconds, external_id,
            json.dumps(config or {}), _now(),
        )
    return dict(row)


async def get_monitor(monitor_id: str):
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM monitors WHERE id = $1", monitor_id)
    return dict(row) if row else None


async def list_monitors(tenant_id: str):
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM monitors WHERE tenant_id = $1 ORDER BY created_at", tenant_id
        )
    return [dict(r) for r in rows]


async def update_monitor_status(monitor_id: str, status: str):
    async with get_db() as conn:
        await conn.execute(
            "UPDATE monitors SET status = $1, updated_at = $2 WHERE id = $3",
            status, _now(), monitor_id,
        )


async def delete_monitor(monitor_id: str):
    async with get_db() as conn:
        await conn.execute("DELETE FROM monitors WHERE id = $1", monitor_id)


# ── Alert Channels ───────────────────────────────────────────────────────────

async def create_alert_channel(
    tenant_id: str,
    name: str,
    channel_type: str,
    config: dict,
    external_id: str | None = None,
):
    import json
    channel_id = _uuid()
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO alert_channels
                (id, tenant_id, name, channel_type, config, external_id, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$7)
            ON CONFLICT (tenant_id, external_id)
                DO UPDATE SET name=EXCLUDED.name, channel_type=EXCLUDED.channel_type,
                    config=EXCLUDED.config, updated_at=EXCLUDED.updated_at
            RETURNING *
            """,
            channel_id, tenant_id, name, channel_type,
            json.dumps(config), external_id, _now(),
        )
    return dict(row)


async def list_alert_channels(tenant_id: str):
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM alert_channels WHERE tenant_id = $1 ORDER BY created_at",
            tenant_id,
        )
    return [dict(r) for r in rows]


# ── Status Pages ─────────────────────────────────────────────────────────────

async def create_status_page(
    tenant_id: str,
    name: str,
    slug: str,
    theme: dict | None = None,
    monitor_ids: list | None = None,
    external_id: str | None = None,
):
    import json
    page_id = _uuid()
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO status_pages
                (id, tenant_id, name, slug, theme, monitor_ids, external_id, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
            ON CONFLICT (tenant_id, external_id)
                DO UPDATE SET name=EXCLUDED.name, slug=EXCLUDED.slug,
                    theme=EXCLUDED.theme, monitor_ids=EXCLUDED.monitor_ids,
                    updated_at=EXCLUDED.updated_at
            RETURNING *
            """,
            page_id, tenant_id, name, slug,
            json.dumps(theme or {}), json.dumps(monitor_ids or []),
            external_id, _now(),
        )
    return dict(row)


async def get_status_page_by_slug(slug: str):
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM status_pages WHERE slug = $1", slug)
    return dict(row) if row else None


# ── Check Results ────────────────────────────────────────────────────────────

async def insert_check_result(
    monitor_id: str,
    status: str,
    response_time_ms: float | None = None,
    status_code: int | None = None,
    error: str | None = None,
):
    result_id = _uuid()
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO check_results
                (id, monitor_id, checked_at, status, response_time_ms, status_code, error)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            result_id, monitor_id, _now(), status, response_time_ms, status_code, error,
        )


async def get_recent_results(monitor_id: str, limit: int = 10):
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM check_results
            WHERE monitor_id = $1
            ORDER BY checked_at DESC
            LIMIT $2
            """,
            monitor_id, limit,
        )
    return [dict(r) for r in rows]


async def get_consecutive_failures(monitor_id: str) -> int:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT status FROM check_results
            WHERE monitor_id = $1
            ORDER BY checked_at DESC
            LIMIT 100
            """,
            monitor_id,
        )
    count = 0
    for r in rows:
        if r["status"] != "up":
            count += 1
        else:
            break
    return count
