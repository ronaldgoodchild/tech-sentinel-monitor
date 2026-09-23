"""ts-provisioner CLI — provision, validate, and check status of Tech Sentinel layouts."""

import json
import sys

import click

from ts_provisioner.client import TSClient
from ts_provisioner.layout_parser import load_layout, validate_layout


@click.group()
@click.option("--api-url", envvar="TS_API_URL", default="http://localhost:8000", help="Control Plane API URL")
@click.pass_context
def cli(ctx, api_url):
    """Tech Sentinel Monitor — Provisioner CLI"""
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url


@cli.command()
@click.argument("layout_file", type=click.Path(exists=True))
@click.option("--token", "-t", multiple=True, help="Token substitution KEY=VALUE")
@click.option("--dry-run", is_flag=True, help="Validate only, don't provision")
@click.pass_context
def provision(ctx, layout_file, token, dry_run):
    """Provision resources from a layout JSON file."""
    # Build token map
    token_map = {}
    for t in token:
        if "=" in t:
            k, v = t.split("=", 1)
            token_map[k] = v

    # Load and validate
    click.echo(f"\U0001F4C4 Loading layout: {layout_file}")
    layout = load_layout(layout_file, token_map)
    errors = validate_layout(layout)

    if errors:
        click.echo("\u274C Validation errors:")
        for e in errors:
            click.echo(f"   - {e}")
        sys.exit(1)

    click.echo("\u2705 Layout validated successfully")

    if dry_run:
        click.echo("\U0001F6AB Dry run — no changes made")
        return

    # Provision
    client = TSClient(ctx.obj["api_url"])

    try:
        # 1. Create tenant
        tenant_cfg = layout["tenant"]
        click.echo(f"\n\U0001F3E2 Creating tenant: {tenant_cfg['name']} ({tenant_cfg['slug']})")
        tenant = client.create_tenant(tenant_cfg["name"], tenant_cfg["slug"])
        api_key = tenant["api_key"]
        click.echo(f"   ID: {tenant['id']}")
        click.echo(f"   API Key: {api_key}")

        # 2. Create monitors
        monitor_ids = {}
        for m in layout.get("monitors", []):
            click.echo(f"\n\U0001F50D Creating monitor: {m['name']} ({m['monitor_type']})")
            monitor_data = {
                "name": m["name"],
                "monitor_type": m["monitor_type"],
                "target": m["target"],
                "interval_seconds": m.get("interval_seconds", 60),
                "timeout_seconds": m.get("timeout_seconds", 10),
                "external_id": m.get("external_id"),
                "config": m.get("config"),
            }
            result = client.create_monitor(api_key, monitor_data)
            monitor_ids[m.get("external_id", m["name"])] = result["id"]
            click.echo(f"   ID: {result['id']}")

        # 3. Create alert channels
        for c in layout.get("alert_channels", []):
            click.echo(f"\n\U0001F514 Creating alert channel: {c['name']} ({c['channel_type']})")
            channel_data = {
                "name": c["name"],
                "channel_type": c["channel_type"],
                "config": c.get("config", {}),
                "external_id": c.get("external_id"),
            }
            result = client.create_alert_channel(api_key, channel_data)
            click.echo(f"   ID: {result['id']}")

        # 4. Create status pages
        for sp in layout.get("status_pages", []):
            # Resolve monitor references
            resolved_ids = []
            for ref in sp.get("monitor_refs", []):
                if ref in monitor_ids:
                    resolved_ids.append(monitor_ids[ref])
            click.echo(f"\n\U0001F4CA Creating status page: {sp['name']} (/{sp['slug']})")
            page_data = {
                "name": sp["name"],
                "slug": sp["slug"],
                "theme": sp.get("theme"),
                "monitor_ids": resolved_ids or sp.get("monitor_ids", []),
                "external_id": sp.get("external_id"),
            }
            result = client.create_status_page(api_key, page_data)
            click.echo(f"   ID: {result['id']}")

        click.echo("\n\u2705 Provisioning complete!")
        click.echo(f"   Tenant: {tenant_cfg['name']}")
        click.echo(f"   Monitors: {len(layout.get('monitors', []))}")
        click.echo(f"   Alert Channels: {len(layout.get('alert_channels', []))}")
        click.echo(f"   Status Pages: {len(layout.get('status_pages', []))}")

    finally:
        client.close()


@cli.command()
@click.argument("layout_file", type=click.Path(exists=True))
@click.option("--token", "-t", multiple=True, help="Token substitution KEY=VALUE")
@click.pass_context
def validate(ctx, layout_file, token):
    """Validate a layout JSON file without provisioning."""
    token_map = {}
    for t in token:
        if "=" in t:
            k, v = t.split("=", 1)
            token_map[k] = v

    layout = load_layout(layout_file, token_map)
    errors = validate_layout(layout)

    if errors:
        click.echo("\u274C Validation errors:")
        for e in errors:
            click.echo(f"   - {e}")
        sys.exit(1)
    else:
        click.echo("\u2705 Layout is valid")
        tenant = layout.get("tenant", {})
        click.echo(f"   Tenant: {tenant.get('name', 'N/A')} ({tenant.get('slug', 'N/A')})")
        click.echo(f"   Monitors: {len(layout.get('monitors', []))}")
        click.echo(f"   Alert Channels: {len(layout.get('alert_channels', []))}")
        click.echo(f"   Status Pages: {len(layout.get('status_pages', []))}")


@cli.command()
@click.pass_context
def status(ctx):
    """Check the Control Plane API health status."""
    client = TSClient(ctx.obj["api_url"])
    try:
        health = client.health()
        click.echo(f"\u2705 Control Plane is healthy: {json.dumps(health)}")

        tenants = client.list_tenants()
        click.echo(f"\n\U0001F3E2 Tenants: {len(tenants)}")
        for t in tenants:
            click.echo(f"   - {t['name']} ({t['slug']})")
    except Exception as e:
        click.echo(f"\u274C Cannot reach Control Plane: {e}")
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    cli()
