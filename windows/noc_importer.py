"""
Tech Sentinel Monitor — NOC Config Importer
============================================
Reads a noc_config.json file (from NOC Dashboard) and provisions
all nodes as monitors in Tech Sentinel Monitor.

Supports:
  - Ping monitors for every node with an IP
  - TCP monitors for every connection (SMB, RDP, FTP, etc.)
  - HTTP monitors for web UIs (manage_url) and hosted services
  - Auto-creates tenant, alert channel, and status page
"""

import json
import logging
import os

from windows.local_database import (
    create_tenant, create_monitor, create_alert_channel,
    create_status_page, list_monitors,
)
from windows.local_queue import enqueue_job

logger = logging.getLogger("ts.noc_importer")


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def import_noc_config(config_path: str, tenant_name: str = "REGTeches / Bay Area Tech",
                       tenant_slug: str = "regteches") -> dict:
    """Import a noc_config.json and create all monitors.

    Returns a summary dict with counts and details.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        noc = json.load(f)

    nodes = noc.get("nodes", [])
    if not nodes:
        return {"error": "No nodes found in config", "monitors_created": 0}

    # 1. Create tenant
    logger.info("Creating tenant: %s (%s)", tenant_name, tenant_slug)
    tenant = create_tenant(name=tenant_name, slug=tenant_slug)
    tenant_id = tenant["id"]

    monitors_created = []
    monitor_ids = {}

    for node in nodes:
        node_name = node.get("name", "Unknown")
        node_ip = node.get("ip")
        connections = node.get("connections", [])
        manage_url = node.get("manage_url")
        hosts = node.get("hosts", [])

        if not node_ip:
            # Static hosts node — process sub-hosts instead
            for host in hosts:
                host_ip = host.get("ip", "")
                host_label = host.get("label", host_ip)
                host_slug = slugify(host_label)

                # Check if IP has a port (like 192.168.1.87:8006)
                if ":" in host_ip and not host_ip.startswith("http"):
                    parts = host_ip.split(":")
                    base_ip = parts[0]
                    port = parts[1]

                    # Ping the base IP
                    ext_id = f"{host_slug}-ping"
                    m = create_monitor(
                        tenant_id=tenant_id, name=f"{host_label} - Ping",
                        monitor_type="ping", target=base_ip,
                        interval_seconds=60, timeout_seconds=10,
                        external_id=ext_id,
                    )
                    monitors_created.append(m)
                    monitor_ids[ext_id] = m["id"]
                    _enqueue(m)

                    # TCP check the port
                    ext_id = f"{host_slug}-tcp-{port}"
                    m = create_monitor(
                        tenant_id=tenant_id, name=f"{host_label} - Port {port}",
                        monitor_type="tcp", target=host_ip,
                        interval_seconds=120, timeout_seconds=10,
                        external_id=ext_id,
                    )
                    monitors_created.append(m)
                    monitor_ids[ext_id] = m["id"]
                    _enqueue(m)
                else:
                    # Just ping it
                    ext_id = f"{host_slug}-ping"
                    m = create_monitor(
                        tenant_id=tenant_id, name=f"{host_label} - Ping",
                        monitor_type="ping", target=host_ip,
                        interval_seconds=60, timeout_seconds=10,
                        external_id=ext_id,
                    )
                    monitors_created.append(m)
                    monitor_ids[ext_id] = m["id"]
                    _enqueue(m)

                    # If host has protocol/port, add HTTP or TCP monitor
                    if host.get("protocol") and host.get("port"):
                        proto = host["protocol"]
                        port = host["port"]
                        url = f"{proto}://{host_ip}:{port}"
                        ext_id = f"{host_slug}-{proto}-{port}"
                        m = create_monitor(
                            tenant_id=tenant_id,
                            name=f"{host_label} - {proto.upper()}:{port}",
                            monitor_type="http" if proto in ("http", "https") else "tcp",
                            target=url if proto in ("http", "https") else f"{host_ip}:{port}",
                            interval_seconds=120, timeout_seconds=10,
                            external_id=ext_id,
                            config={"method": "GET", "expected_status": 200} if proto in ("http", "https") else None,
                        )
                        monitors_created.append(m)
                        monitor_ids[ext_id] = m["id"]
                        _enqueue(m)
            continue

        node_slug = slugify(node_name)

        # ── Ping monitor for every node with an IP ────────────────────────
        ext_id = f"{node_slug}-ping"
        m = create_monitor(
            tenant_id=tenant_id, name=f"{node_name} - Ping",
            monitor_type="ping", target=node_ip,
            interval_seconds=60, timeout_seconds=10,
            external_id=ext_id,
        )
        monitors_created.append(m)
        monitor_ids[ext_id] = m["id"]
        _enqueue(m)

        # ── TCP monitors for each connection ──────────────────────────────
        for conn in connections:
            conn_type = conn.get("type", "TCP")
            port = conn.get("port")
            if not port:
                continue

            ext_id = f"{node_slug}-{conn_type.lower()}-{port}"
            m = create_monitor(
                tenant_id=tenant_id,
                name=f"{node_name} - {conn_type}:{port}",
                monitor_type="tcp",
                target=f"{node_ip}:{port}",
                interval_seconds=120, timeout_seconds=5,
                external_id=ext_id,
            )
            monitors_created.append(m)
            monitor_ids[ext_id] = m["id"]
            _enqueue(m)

        # ── HTTP monitor for manage_url ───────────────────────────────────
        if manage_url and manage_url.startswith("http"):
            ext_id = f"{node_slug}-webui"
            m = create_monitor(
                tenant_id=tenant_id,
                name=f"{node_name} - Web UI",
                monitor_type="http",
                target=manage_url,
                interval_seconds=120, timeout_seconds=10,
                external_id=ext_id,
                config={"method": "GET", "expected_status": 200},
            )
            monitors_created.append(m)
            monitor_ids[ext_id] = m["id"]
            _enqueue(m)

        # ── HTTP monitors for hosted services (Sonarr, Radarr, etc.) ─────
        for host in hosts:
            host_label = host.get("label", "Service")
            host_ip = host.get("ip", node_ip)
            proto = host.get("protocol", "http")
            port = host.get("port")
            if not port:
                continue

            url = f"{proto}://{host_ip}:{port}"
            host_slug = slugify(host_label)
            ext_id = f"{node_slug}-{host_slug}"

            m = create_monitor(
                tenant_id=tenant_id,
                name=host_label,
                monitor_type="http" if proto in ("http", "https") else "tcp",
                target=url if proto in ("http", "https") else f"{host_ip}:{port}",
                interval_seconds=120, timeout_seconds=10,
                external_id=ext_id,
                config={"method": "GET", "expected_status": 200} if proto in ("http", "https") else None,
            )
            monitors_created.append(m)
            monitor_ids[ext_id] = m["id"]
            _enqueue(m)

    # 2. Create alert channel
    channel = create_alert_channel(
        tenant_id=tenant_id, name="REGTeches Alerts",
        channel_type="webhook",
        config={"url": ""},
        external_id="regteches-alerts",
    )

    # 3. Create status page with ALL monitors
    all_monitor_ids = list(monitor_ids.values())
    status_page = create_status_page(
        tenant_id=tenant_id,
        name="REGTeches Network Status",
        slug="regteches-status",
        theme={
            "bg_primary": "#0f1117",
            "bg_secondary": "#1a1d27",
            "bg_card": "#222636",
            "text_primary": "#e1e4ed",
            "text_secondary": "#8b8fa3",
            "accent": "#3b82f6",
        },
        monitor_ids=all_monitor_ids,
        external_id="regteches-status-page",
    )

    summary = {
        "tenant": tenant,
        "monitors_created": len(monitors_created),
        "monitor_names": [m["name"] for m in monitors_created],
        "alert_channel": channel["name"],
        "status_page_url": f"/status/{status_page['slug']}",
    }

    logger.info("NOC import complete: %d monitors created", len(monitors_created))
    return summary


def _enqueue(monitor: dict):
    """Enqueue a monitor for the local probe worker."""
    enqueue_job({
        "monitor_id": monitor["id"],
        "tenant_id": monitor["tenant_id"],
        "monitor_type": monitor["monitor_type"],
        "target": monitor["target"],
        "interval_seconds": str(monitor["interval_seconds"]),
        "timeout_seconds": str(monitor["timeout_seconds"]),
        "config": monitor.get("config", "{}"),
    })
