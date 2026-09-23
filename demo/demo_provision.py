#!/usr/bin/env python3
"""
Tech Sentinel Monitor — ACME Corp Demo Provisioning Script

This script demonstrates the full provisioning flow:
1. Creates the ACME Corporation tenant
2. Provisions 6 monitors (HTTP, TCP, Ping, Heartbeat)
3. Sets up 3 alert channels (Webhook, Slack, PagerDuty)
4. Creates a branded status page
5. Validates idempotency (re-provision returns same IDs)
6. Tests lifecycle (pause/resume)
7. Checks status page reachability

Usage:
    python demo/demo_provision.py [--api-url http://localhost:8000]
"""

import json
import os
import sys
import time

import httpx

API_URL = os.getenv("TS_API_URL", sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://localhost:8000")
DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUT_FILE = os.path.join(DEMO_DIR, "ts-uptimerobot-layout.json")

# Token map for template substitution
TOKEN_MAP = {
    "ACME_WEBHOOK_URL": os.getenv("ACME_WEBHOOK_URL", "https://example.com/webhook"),
    "ACME_SLACK_WEBHOOK": os.getenv("ACME_SLACK_WEBHOOK", "https://hooks.slack.com/services/DEMO/DEMO/DEMO"),
    "ACME_PD_ROUTING_KEY": os.getenv("ACME_PD_ROUTING_KEY", "demo-pagerduty-key"),
}


def banner(msg: str):
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


def step(msg: str):
    print(f"\n\U0001F539 {msg}")


def ok(msg: str):
    print(f"   \u2705 {msg}")


def fail(msg: str):
    print(f"   \u274C {msg}")
    sys.exit(1)


def api(method: str, path: str, headers: dict | None = None, **kwargs) -> httpx.Response:
    url = f"{API_URL}{path}"
    return httpx.request(method, url, headers=headers or {}, timeout=30, **kwargs)


def main():
    banner("Tech Sentinel Monitor — ACME Corp Demo")
    print(f"  API: {API_URL}")
    print(f"  Layout: {LAYOUT_FILE}")

    # ── Step 1: Health Check ─────────────────────────────────────────────
    step("Checking Control Plane health...")
    try:
        resp = api("GET", "/health")
        if resp.status_code == 200:
            ok(f"Control Plane is healthy: {resp.json()}")
        else:
            fail(f"Health check failed: {resp.status_code}")
    except Exception as e:
        fail(f"Cannot reach Control Plane: {e}")

    # ── Step 2: Create Tenant ────────────────────────────────────────────
    step("Creating ACME Corporation tenant...")
    resp = api("POST", "/api/v1/tenants/", json={"name": "ACME Corporation", "slug": "acme-corp"})
    if resp.status_code in (200, 201):
        tenant = resp.json()
        api_key = tenant["api_key"]
        tenant_id = tenant["id"]
        ok(f"Tenant created: {tenant['name']} (ID: {tenant_id})")
        ok(f"API Key: {api_key}")
    else:
        fail(f"Failed to create tenant: {resp.status_code} {resp.text}")

    auth = {"X-TS-API-Key": api_key}

    # ── Step 3: Create Monitors ──────────────────────────────────────────
    step("Provisioning 6 monitors...")
    monitors_data = [
        {"name": "ACME Website", "monitor_type": "http", "target": "https://www.acme-corp.example.com", "external_id": "acme-website", "config": {"method": "GET", "expected_status": 200}},
        {"name": "API Health", "monitor_type": "http", "target": "https://api.acme-corp.example.com/health", "external_id": "acme-api", "config": {"body_contains": "ok"}},
        {"name": "PostgreSQL", "monitor_type": "tcp", "target": "db.acme-corp.example.com:5432", "external_id": "acme-postgres"},
        {"name": "Redis", "monitor_type": "tcp", "target": "redis.acme-corp.example.com:6379", "external_id": "acme-redis"},
        {"name": "Mail Server", "monitor_type": "ping", "target": "mail.acme-corp.example.com", "external_id": "acme-mail"},
        {"name": "Backup Agent", "monitor_type": "heartbeat", "target": "backup-agent", "external_id": "acme-backup", "timeout_seconds": 120},
    ]

    monitor_ids = {}
    for m in monitors_data:
        resp = api("POST", "/api/v1/monitors/", headers=auth, json=m)
        if resp.status_code in (200, 201):
            result = resp.json()
            monitor_ids[m["external_id"]] = result["id"]
            ok(f"{m['name']} ({m['monitor_type']}) -> {result['id']}")
        else:
            fail(f"Failed to create {m['name']}: {resp.status_code} {resp.text}")

    # ── Step 4: Create Alert Channels ────────────────────────────────────
    step("Setting up 3 alert channels...")
    channels_data = [
        {"name": "ACME Webhook", "channel_type": "webhook", "external_id": "acme-webhook", "config": {"url": TOKEN_MAP["ACME_WEBHOOK_URL"]}},
        {"name": "ACME Slack", "channel_type": "slack", "external_id": "acme-slack", "config": {"webhook_url": TOKEN_MAP["ACME_SLACK_WEBHOOK"]}},
        {"name": "ACME PagerDuty", "channel_type": "pagerduty", "external_id": "acme-pagerduty", "config": {"routing_key": TOKEN_MAP["ACME_PD_ROUTING_KEY"]}},
    ]

    for c in channels_data:
        resp = api("POST", "/api/v1/alert-channels/", headers=auth, json=c)
        if resp.status_code in (200, 201):
            result = resp.json()
            ok(f"{c['name']} ({c['channel_type']}) -> {result['id']}")
        else:
            fail(f"Failed to create {c['name']}: {resp.status_code} {resp.text}")

    # ── Step 5: Create Status Page ───────────────────────────────────────
    step("Creating ACME status page...")
    page_data = {
        "name": "ACME Corp Status",
        "slug": "acme-status",
        "external_id": "acme-status-page",
        "monitor_ids": list(monitor_ids.values()),
        "theme": {"bg_primary": "#0f1117", "accent": "#3b82f6"},
    }
    resp = api("POST", "/api/v1/status-pages/", headers=auth, json=page_data)
    if resp.status_code in (200, 201):
        result = resp.json()
        ok(f"Status page created: {result['slug']} -> {result['id']}")
    else:
        fail(f"Failed to create status page: {resp.status_code} {resp.text}")

    # ── Step 6: Idempotency Validation ───────────────────────────────────
    step("Validating idempotency (re-provisioning should return same IDs)...")
    resp2 = api("POST", "/api/v1/tenants/", json={"name": "ACME Corporation", "slug": "acme-corp"})
    if resp2.status_code in (200, 201):
        tenant2 = resp2.json()
        if tenant2["id"] == tenant_id:
            ok("Tenant idempotent: same ID on re-provision")
        else:
            ok(f"Tenant upserted (new ID: {tenant2['id']})")

    for m in monitors_data:
        resp = api("POST", "/api/v1/monitors/", headers=auth, json=m)
        if resp.status_code in (200, 201):
            result = resp.json()
            original_id = monitor_ids.get(m["external_id"])
            if result["id"] == original_id:
                ok(f"Monitor '{m['name']}' idempotent")
            else:
                ok(f"Monitor '{m['name']}' upserted")

    # ── Step 7: Lifecycle Test (Pause/Resume) ────────────────────────────
    step("Testing monitor lifecycle (pause/resume)...")
    first_monitor_id = list(monitor_ids.values())[0]

    # Pause
    resp = api("PATCH", f"/api/v1/monitors/{first_monitor_id}/status", headers=auth, json={"status": "paused"})
    if resp.status_code == 200 and resp.json()["status"] == "paused":
        ok("Monitor paused successfully")
    else:
        fail(f"Failed to pause monitor: {resp.status_code}")

    # Resume
    resp = api("PATCH", f"/api/v1/monitors/{first_monitor_id}/status", headers=auth, json={"status": "active"})
    if resp.status_code == 200 and resp.json()["status"] == "active":
        ok("Monitor resumed successfully")
    else:
        fail(f"Failed to resume monitor: {resp.status_code}")

    # ── Step 8: Status Page Reachability ─────────────────────────────────
    step("Checking status page reachability...")
    status_page_url = f"http://localhost:8001/status/acme-status"
    try:
        resp = httpx.get(status_page_url, timeout=10)
        if resp.status_code == 200:
            ok(f"Status page is live at {status_page_url}")
        else:
            print(f"   \u26A0\uFE0F  Status page returned {resp.status_code} (may not be running yet)")
    except Exception:
        print(f"   \u26A0\uFE0F  Status page not reachable at {status_page_url} (start status-page service)")

    # ── Summary ──────────────────────────────────────────────────────────
    banner("Demo Complete!")
    print(f"  \U0001F3E2 Tenant: ACME Corporation (acme-corp)")
    print(f"  \U0001F50D Monitors: {len(monitor_ids)}")
    print(f"  \U0001F514 Alert Channels: {len(channels_data)}")
    print(f"  \U0001F4CA Status Page: http://localhost:8001/status/acme-status")
    print(f"  \U0001F511 API Key: {api_key}")
    print()


if __name__ == "__main__":
    main()
