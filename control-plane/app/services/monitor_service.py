"""Monitor scheduling — publishes jobs to Redis Streams for probe workers."""


from app.database import get_redis

STREAM_KEY = "ts:probe:jobs"


async def schedule_monitor(monitor: dict):
    """Publish a monitor job to the Redis stream for probe workers to pick up."""
    redis = await get_redis()
    job = {
        "monitor_id": monitor["id"],
        "tenant_id": monitor["tenant_id"],
        "monitor_type": monitor["monitor_type"],
        "target": monitor["target"],
        "interval_seconds": str(monitor["interval_seconds"]),
        "timeout_seconds": str(monitor["timeout_seconds"]),
        "config": monitor.get("config", "{}"),
    }
    await redis.xadd(STREAM_KEY, job)


async def schedule_all_active_monitors():
    """Re-schedule all active monitors — called on startup."""
    from app.models import list_monitors, list_tenants

    tenants = await list_tenants()
    for tenant in tenants:
        monitors = await list_monitors(tenant["id"])
        for monitor in monitors:
            if monitor["status"] == "active":
                await schedule_monitor(monitor)
