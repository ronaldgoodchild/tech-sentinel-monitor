"""Heartbeat probe — passive check that expects the monitored service to call in.

The heartbeat probe checks the database for the most recent check-in.
If the last heartbeat is older than the interval, the monitor is considered down.
"""

from datetime import datetime, timezone


async def heartbeat_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    """Check if a heartbeat has been received within the expected interval.

    For heartbeat monitors, the 'target' is the monitor_id itself.
    The actual check-in happens via the /api/v1/heartbeat/{monitor_id} endpoint.
    This probe just verifies the last check-in is recent enough.
    """
    from worker.persistence import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT checked_at FROM check_results
            WHERE monitor_id = $1 AND status = 'up'
            ORDER BY checked_at DESC
            LIMIT 1
            """,
            target,
        )

    if row is None:
        return {
            "status": "down",
            "response_time_ms": 0,
            "status_code": None,
            "error": "No heartbeat received yet",
        }

    last_beat = row["checked_at"]
    now = datetime.now(timezone.utc)
    age_seconds = (now - last_beat).total_seconds()

    # If last heartbeat is older than timeout * 2 (grace period), mark as down
    grace = timeout * 2
    if age_seconds > grace:
        return {
            "status": "down",
            "response_time_ms": 0,
            "status_code": None,
            "error": f"Last heartbeat was {int(age_seconds)}s ago (grace: {grace}s)",
        }

    return {
        "status": "up",
        "response_time_ms": 0,
        "status_code": None,
        "error": None,
    }
