"""Alert engine — evaluates consecutive failures and triggers notifications."""

import logging

from app.config import settings
from app.models import get_consecutive_failures, get_monitor, list_alert_channels
from app.services.webhook_dispatcher import dispatch_alert

logger = logging.getLogger("ts.alert_engine")


async def evaluate_alert(monitor_id: str, check_status: str):
    """Check if a monitor has breached the consecutive failure threshold."""
    monitor = await get_monitor(monitor_id)
    if not monitor:
        return

    failures = await get_consecutive_failures(monitor_id)
    threshold = settings.ts_alert_consecutive_failures

    if check_status != "up" and failures >= threshold:
        # Breached threshold — send alert
        channels = await list_alert_channels(monitor["tenant_id"])
        for channel in channels:
            try:
                await dispatch_alert(
                    channel=channel,
                    monitor=monitor,
                    failures=failures,
                    event="alert",
                )
            except Exception as e:
                logger.error(f"Failed to dispatch alert to {channel['name']}: {e}")

    elif check_status == "up" and failures == 0:
        # Just recovered — check if previous state was down
        from app.models import get_recent_results
        results = await get_recent_results(monitor_id, limit=2)
        if len(results) >= 2 and results[1]["status"] != "up":
            # Recovery notification
            channels = await list_alert_channels(monitor["tenant_id"])
            for channel in channels:
                try:
                    await dispatch_alert(
                        channel=channel,
                        monitor=monitor,
                        failures=0,
                        event="recovery",
                    )
                except Exception as e:
                    logger.error(f"Failed to dispatch recovery to {channel['name']}: {e}")
