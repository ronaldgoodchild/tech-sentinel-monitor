"""Webhook dispatcher — sends alerts to webhook, Slack, PagerDuty, TS Automation."""

import json
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger("ts.webhook_dispatcher")


async def dispatch_alert(channel: dict, monitor: dict, failures: int, event: str):
    """Dispatch an alert or recovery notification to the given channel."""
    config = json.loads(channel["config"]) if isinstance(channel["config"], str) else channel["config"]
    channel_type = channel["channel_type"]

    payload = _build_payload(monitor, failures, event)

    if channel_type == "webhook":
        await _send_webhook(config.get("url", ""), payload)
    elif channel_type == "slack":
        await _send_slack(config.get("webhook_url", settings.ts_slack_webhook_url), payload)
    elif channel_type == "pagerduty":
        await _send_pagerduty(
            config.get("routing_key", settings.ts_pagerduty_routing_key),
            monitor, event,
        )
    elif channel_type == "ts_automation":
        await _send_ts_automation(monitor, event)


def _build_payload(monitor: dict, failures: int, event: str) -> dict:
    emoji = "\u2705" if event == "recovery" else "\U0001f6a8"
    status_text = "RECOVERED" if event == "recovery" else "DOWN"
    return {
        "event": event,
        "monitor_id": monitor["id"],
        "monitor_name": monitor["name"],
        "monitor_type": monitor["monitor_type"],
        "target": monitor["target"],
        "status": status_text,
        "consecutive_failures": failures,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": f"{emoji} [{status_text}] {monitor['name']} ({monitor['target']}) — {failures} consecutive failures",
    }


async def _send_webhook(url: str, payload: dict):
    if not url:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        logger.info(f"Webhook {url} responded {resp.status_code}")


async def _send_slack(webhook_url: str, payload: dict):
    if not webhook_url:
        return
    slack_payload = {
        "text": payload["message"],
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": payload["message"]},
            }
        ],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook_url, json=slack_payload)
        logger.info(f"Slack responded {resp.status_code}")


async def _send_pagerduty(routing_key: str, monitor: dict, event: str):
    if not routing_key:
        return
    pd_event = "resolve" if event == "recovery" else "trigger"
    payload = {
        "routing_key": routing_key,
        "event_action": pd_event,
        "dedup_key": f"ts-monitor-{monitor['id']}",
        "payload": {
            "summary": f"Tech Sentinel: {monitor['name']} is {'UP' if event == 'recovery' else 'DOWN'}",
            "source": "tech-sentinel-monitor",
            "severity": "critical" if event != "recovery" else "info",
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload,
        )
        logger.info(f"PagerDuty responded {resp.status_code}")


async def _send_ts_automation(monitor: dict, event: str):
    url = settings.ts_automation_url
    api_key = settings.ts_automation_api_key
    if not url:
        return
    payload = {
        "event": event,
        "monitor_id": monitor["id"],
        "monitor_name": monitor["name"],
        "target": monitor["target"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload, headers=headers)
        logger.info(f"TS Automation responded {resp.status_code}")
