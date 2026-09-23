"""
Tech Sentinel Monitor — Local Status Page Server
Standalone version that reads directly from SQLite instead of calling the API.
Features: 3-across grid, clickable cards, edit/manage monitors.
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from windows.local_version_control import APP_VERSION


# ── Shared CSS ───────────────────────────────────────────────────────────────

SHARED_CSS_TEMPLATE = """
  :root {
    --bg-primary: %%bg_primary%%; --bg-secondary: %%bg_secondary%%;
    --bg-card: %%bg_card%%; --text-primary: %%text_primary%%;
    --text-secondary: %%text_secondary%%; --accent: %%accent%%;
    --green: #22c55e; --red: #ef4444; --yellow: #f59e0b; --gray: #6b7280;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary); color: var(--text-primary); min-height: 100vh;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .container { max-width: 1100px; margin: 0 auto; padding: 2rem 1rem; }
  header { text-align: center; margin-bottom: 1.5rem; }
  header h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  header .tenant { color: var(--text-secondary); font-size: 0.875rem; }
  .overall-status {
    background: var(--bg-secondary); border-radius: 12px;
    padding: 1.25rem; text-align: center; margin-bottom: 1.5rem;
    border: 1px solid rgba(255,255,255,0.05);
  }
  .badge {
    display: inline-block; padding: 0.4rem 1.2rem;
    border-radius: 20px; font-weight: 600; font-size: 1rem;
  }
  .badge-operational { background: rgba(34,197,94,0.15); color: var(--green); }
  .badge-outage { background: rgba(239,68,68,0.15); color: var(--red); }
  .badge-degraded { background: rgba(245,158,11,0.15); color: var(--yellow); }
  .badge-unknown { background: rgba(107,114,128,0.15); color: var(--gray); }

  /* ── 3-across grid ─────────────────────────────────────────────────── */
  .monitors-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
  }
  @media (max-width: 900px) { .monitors-grid { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 560px) { .monitors-grid { grid-template-columns: 1fr; } }

  .monitor-card {
    background: var(--bg-card); border-radius: 10px;
    padding: 1rem 1.1rem; display: flex; flex-direction: column;
    border: 1px solid rgba(255,255,255,0.04);
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
    cursor: pointer; text-decoration: none; color: inherit;
    min-height: 110px; justify-content: space-between;
  }
  .monitor-card:hover {
    border-color: var(--accent); transform: translateY(-3px);
    box-shadow: 0 6px 20px rgba(59,130,246,0.15);
    text-decoration: none;
  }
  .monitor-top { display: flex; justify-content: space-between; align-items: flex-start; }
  .monitor-name { font-size: 0.95rem; font-weight: 600; line-height: 1.3; }
  .monitor-meta { font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.3rem; }
  .monitor-target { font-size: 0.75rem; color: var(--text-secondary); margin-top: auto; padding-top: 0.5rem;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .monitor-bottom { display: flex; justify-content: space-between; align-items: center; margin-top: 0.4rem; }
  .response-time { font-size: 0.78rem; color: var(--text-secondary); }
  .open-link {
    display: inline-block; margin-left: 0.4rem; font-size: 0.85rem;
    color: var(--accent); background: rgba(59,130,246,0.1);
    padding: 1px 6px; border-radius: 4px; font-weight: 700;
    transition: background 0.2s, color 0.2s; vertical-align: middle;
  }
  .open-link:hover { background: var(--accent); color: white; text-decoration: none; }
  .status-badge { display: flex; align-items: center; gap: 0.3rem; font-size: 0.8rem; text-transform: capitalize; }
  .status-dot { width: 9px; height: 9px; border-radius: 50%; }
  .dot-up { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot-down { background: var(--red); box-shadow: 0 0 6px var(--red); }
  .dot-timeout { background: var(--red); box-shadow: 0 0 6px var(--red); }
  .dot-unknown { background: var(--gray); }
  .dot-pending { background: var(--yellow); box-shadow: 0 0 6px var(--yellow); }

  footer {
    text-align: center; margin-top: 2rem; padding-top: 1rem;
    border-top: 1px solid rgba(255,255,255,0.05);
    color: var(--text-secondary); font-size: 0.75rem;
  }
  .toolbar { display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem; }
  .btn {
    display: inline-block; padding: 0.5rem 1rem; border-radius: 8px;
    font-size: 0.85rem; font-weight: 600; cursor: pointer;
    border: 1px solid var(--accent); color: var(--accent);
    background: transparent; text-decoration: none;
    transition: background 0.2s, color 0.2s;
  }
  .btn:hover { background: var(--accent); color: white; text-decoration: none; }
  .btn-primary { background: var(--accent); color: white; }
  .btn-danger { border-color: var(--red); color: var(--red); }
  .btn-danger:hover { background: var(--red); color: white; }
  .count-badge { background: var(--bg-secondary); padding: 0.3rem 0.8rem;
    border-radius: 12px; font-size: 0.8rem; color: var(--text-secondary); }
"""


def _render_css(theme_vars: dict) -> str:
    """Render SHARED_CSS_TEMPLATE with theme variables using safe %%key%% replacement."""
    css = SHARED_CSS_TEMPLATE
    for key, val in theme_vars.items():
        css = css.replace(f"%%{key}%%", val)
    return css


def _build_clickable_url(target: str, monitor_type: str) -> str:
    """Build a clickable URL from a monitor target."""
    if monitor_type == "http":
        return target
    elif monitor_type == "tcp":
        # For TCP, try to make a useful link
        if ":" in target:
            host, port = target.rsplit(":", 1)
            port_int = int(port) if port.isdigit() else 0
            if port_int in (80, 8080, 8000, 8001, 8989, 7878, 8686, 32400, 5000):
                return f"http://{target}"
            elif port_int in (443, 5001, 8006, 8443, 9090):
                return f"https://{target}"
            elif port_int == 3389:
                return ""  # RDP, not a web link
            elif port_int == 445:
                return ""  # SMB, not a web link
            else:
                return f"http://{target}"
        return ""
    elif monitor_type == "ping":
        return f"http://{target}"
    return ""


def _build_sparkline_svg(data_points: list[dict], width: int = 120, height: int = 30) -> str:
    """Build an inline SVG sparkline from response time data."""
    if not data_points or len(data_points) < 2:
        return ""
    values = [d.get("response_time_ms", 0) or 0 for d in data_points]
    max_val = max(values) or 1
    min_val = min(values)
    val_range = max_val - min_val or 1

    step = width / max(len(values) - 1, 1)
    points = []
    for i, v in enumerate(values):
        x = round(i * step, 1)
        y = round(height - ((v - min_val) / val_range) * (height - 4) - 2, 1)
        points.append(f"{x},{y}")

    polyline = " ".join(points)
    # Gradient fill area
    fill_points = f"0,{height} {polyline} {round((len(values)-1)*step,1)},{height}"

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle;margin-top:4px">'
        f'<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#3b82f6" stop-opacity="0.3"/>'
        f'<stop offset="100%" stop-color="#3b82f6" stop-opacity="0.0"/>'
        f'</linearGradient></defs>'
        f'<polygon points="{fill_points}" fill="url(#sg)"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#3b82f6" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _format_uptime_badge(pct: float) -> str:
    """Return colored uptime badge HTML."""
    if pct >= 99.9:
        color = "#22c55e"
    elif pct >= 99.0:
        color = "#f59e0b"
    elif pct >= 95.0:
        color = "#f97316"
    else:
        color = "#ef4444"
    return (f'<span style="background:rgba({_hex_to_rgb(color)},0.15);color:{color};'
            f'padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:600">'
            f'{pct:.2f}%</span>')


def _hex_to_rgb(hex_color: str) -> str:
    """Convert #rrggbb to r,g,b string."""
    h = hex_color.lstrip("#")
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"


def _get_branding() -> dict:
    """Get branding config as a dict, with safe defaults."""
    try:
        from windows.local_branding import get_branding_config, CREATOR_CREDIT
        cfg = get_branding_config()
        d = cfg.to_dict()
        d["header_html"] = cfg.get_header_html()
        d["footer_html"] = cfg.get_footer_html()
        d["creator_credit"] = CREATOR_CREDIT
        return d
    except Exception:
        return {
            "app_name": "Tech Sentinel Monitor", "company_name": "",
            "accent_color": "#3b82f6", "logo_url": "", "favicon_url": "",
            "custom_footer": "",
            "header_html": "🛡️ Tech Sentinel Monitor",
            "footer_html": "Powered by Tech Sentinel Monitor &mdash; <span style='opacity:0.7'>Created by Ronald Goodchild / REGTeches</span>",
            "creator_credit": "Created by Ronald Goodchild / REGTeches",
        }


def create_status_app() -> FastAPI:
    app = FastAPI(title="Tech Sentinel — Local Status Page", version=APP_VERSION)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "status-page-local"}

    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Landing page listing all available status pages."""
        from windows.local_database import _get_conn
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT sp.slug, sp.name, t.name as tenant_name "
                "FROM status_pages sp JOIN tenants t ON sp.tenant_id = t.id "
                "ORDER BY sp.created_at DESC"
            ).fetchall()
            pages = [dict(r) for r in rows]
        except Exception:
            pages = []

        page_links = ""
        for p in pages:
            page_links += f"""
            <a href="/status/{p['slug']}" class="page-card">
                <div class="page-name">📊 {p['name']}</div>
                <div class="page-tenant">{p['tenant_name']}</div>
                <div class="page-url">/status/{p['slug']}</div>
            </a>"""

        if not page_links:
            page_links = """
            <div class="empty">
                <p>🔍 No status pages created yet</p>
                <p style="font-size:0.9rem;color:#8b8fa3">
                    Use the launcher GUI to import your NOC config<br>
                    or create monitors via the
                    <a href="/manage">API / Manage</a>
                </p>
            </div>"""

        return f"""<!DOCTYPE html>
<html><head>
<title>Tech Sentinel Monitor — Status Pages</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e1e4ed; margin: 0; min-height: 100vh; }}
  .container {{ max-width: 700px; margin: 0 auto; padding: 3rem 1rem; }}
  h1 {{ color: #3b82f6; text-align: center; margin-bottom: 0.5rem; }}
  .subtitle {{ text-align: center; color: #8b8fa3; margin-bottom: 2rem; }}
  a {{ color: #3b82f6; text-decoration: none; }}
  .page-card {{
    display: block; background: #1a1d27; border-radius: 12px;
    padding: 1.5rem; margin-bottom: 1rem; border: 1px solid #333750;
    transition: border-color 0.2s, transform 0.2s;
  }}
  .page-card:hover {{ border-color: #3b82f6; transform: translateY(-2px); }}
  .page-name {{ font-size: 1.2rem; font-weight: 600; color: #e1e4ed; margin-bottom: 0.3rem; }}
  .page-tenant {{ color: #8b8fa3; font-size: 0.9rem; }}
  .page-url {{ color: #3b82f6; font-size: 0.85rem; margin-top: 0.5rem; font-family: monospace; }}
  .empty {{ text-align: center; padding: 3rem; color: #8b8fa3; }}
  .empty p {{ margin: 0.5rem 0; }}
  code {{ background: #222636; padding: 3px 8px; border-radius: 4px; }}
  .nav {{ text-align: center; margin-top: 2rem; color: #555; font-size: 0.85rem; }}
</style>
</head><body>
<div class="container">
  <h1>🛡️ Tech Sentinel Monitor</h1>
  <p class="subtitle">Public Status Pages</p>
  {page_links}
  <div class="nav">
    <a id="cp-link" href="/manage">⚙️ Control Plane</a> &nbsp;|&nbsp;
    <a id="api-link" href="/manage">📖 API Docs</a> &nbsp;|&nbsp;
    <a href="/manage">🔧 Manage Monitors</a>
    <script>
      (function(){{
        var h=location.hostname||'localhost';
        document.getElementById('cp-link').href='http://'+h+':8000';
        document.getElementById('api-link').href='http://'+h+':8000/docs';
      }})();
    </script>
    <p style="margin-top:1rem">Tech Sentinel Monitor v{APP_VERSION} — REGTeches</p>
  </div>
</div>
</body></html>"""

    # ── Status Page (3-across grid, clickable, sparklines, uptime) ─────
    @app.get("/status/{slug}", response_class=HTMLResponse)
    async def status_page(slug: str):
        from windows.local_database import (
            get_status_page_by_slug, get_tenant, get_monitor, get_recent_results,
            get_uptime_percent, get_response_time_series, is_in_maintenance,
        )

        page = get_status_page_by_slug(slug)
        if not page:
            return HTMLResponse("<h1>Status page not found</h1>", status_code=404)

        monitor_ids = json.loads(page.get("monitor_ids", "[]")) if isinstance(page.get("monitor_ids"), str) else page.get("monitor_ids", [])
        theme = json.loads(page.get("theme", "{}")) if isinstance(page.get("theme"), str) else page.get("theme", {})
        tenant = get_tenant(page["tenant_id"])
        tenant_name = tenant["name"] if tenant else "Unknown"

        # Group monitors by group_name, agents first
        groups: dict[str, list] = {}
        agent_ids = set()  # track which monitors are agents
        statuses = []
        up_count = down_count = 0

        # Sort monitor_ids so heartbeat (agent) monitors come first
        all_monitors = []
        for mid in monitor_ids:
            m = get_monitor(mid)
            if m:
                all_monitors.append((mid, m))
        all_monitors.sort(key=lambda x: (0 if x[1]["monitor_type"] == "heartbeat" else 1, x[1].get("group_name", "")))

        for mid, m in all_monitors:

            # Check maintenance window
            mw = is_in_maintenance(mid)

            results = get_recent_results(mid, limit=1)
            if mw:
                s = "maintenance"
            elif results:
                r = results[0]
                s = r["status"]
            else:
                s = "pending"

            # Uptime percentage
            uptime_24h = get_uptime_percent(mid, 24)

            # Sparkline data
            series = get_response_time_series(mid, 30)
            sparkline = _build_sparkline_svg(series)

            resp_ms = results[0].get("response_time_ms") if results else None
            resp_text = f'<span class="response-time">{resp_ms:.0f}ms</span>' if resp_ms else ""
            uptime_badge = _format_uptime_badge(uptime_24h) if uptime_24h > 0 else ""

            # SSL info
            ssl_expiry = m.get("ssl_expiry", "")
            ssl_badge = ""
            if ssl_expiry:
                try:
                    from datetime import datetime as dt
                    days_left = (dt.fromisoformat(ssl_expiry) - dt.now()).days
                    if days_left <= 14:
                        ssl_badge = f'<span style="color:#ef4444;font-size:0.7rem">🔐 {days_left}d</span>'
                    elif days_left <= 30:
                        ssl_badge = f'<span style="color:#f59e0b;font-size:0.7rem">🔐 {days_left}d</span>'
                except Exception:
                    pass

            statuses.append(s)
            if s == "up":
                up_count += 1
            elif s in ("down", "timeout"):
                down_count += 1

            if m["monitor_type"] == "heartbeat":
                group_name = m.get("group_name", "") or "🖥️ Agents"
            else:
                group_name = m.get("group_name", "") or "Monitors"
            type_icons = {"http": "🌐", "tcp": "🔌", "ping": "📡", "heartbeat": "💓"}
            icon = type_icons.get(m["monitor_type"], "📍")

            # Maintenance badge overrides status
            if s == "maintenance":
                dot_class = "dot-unknown"
                status_text = "🔧 maintenance"
            else:
                dot_class = f"dot-{s}"
                status_text = s

            # Build clickable URL for opening the actual service
            click_url = _build_clickable_url(m["target"], m["monitor_type"])
            open_link = ""
            if click_url:
                open_link = (
                    f'<a href="{click_url}" target="_blank" class="open-link" '
                    f'onclick="event.stopPropagation()" title="Open {m["target"]}">↗</a>'
                )

            card_html = f"""
            <div class="monitor-card" data-monitor-id="{mid}" onclick="window.location='/monitor/{mid}'" role="link">
                <div class="monitor-top">
                    <div>
                        <div class="monitor-name">{icon} {m['name']} {ssl_badge}</div>
                        <div class="monitor-meta">{m['monitor_type'].upper()} {uptime_badge}</div>
                    </div>
                    <div class="status-badge">
                        <span class="status-dot {dot_class}"></span> <span class="status-text">{status_text}</span>
                    </div>
                </div>
                <div class="monitor-target" title="{m['target']}">{m['target']} {open_link}</div>
                <div class="monitor-bottom">
                    <span class="response-time">{resp_text}</span>
                    {sparkline}
                </div>
            </div>"""

            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(card_html)

        # Build grouped HTML
        monitors_html = ""
        for gname, cards in groups.items():
            if len(groups) > 1:
                monitors_html += f'<h3 style="color:var(--text-secondary);margin:1.2rem 0 0.5rem;font-size:0.9rem;text-transform:uppercase;letter-spacing:0.05em">{gname}</h3>'
            monitors_html += '<div class="monitors-grid">' + "".join(cards) + '</div>'

        total = len(statuses)
        if all(s == "up" for s in statuses) and statuses:
            overall_class, overall_text = "operational", f"✅ All {total} Systems Operational"
        elif any(s in ("down", "timeout") for s in statuses):
            overall_class, overall_text = "outage", f"🚨 {down_count} of {total} Systems Down"
        elif any(s == "degraded" for s in statuses):
            overall_class, overall_text = "degraded", "⚠️ Degraded Performance"
        else:
            overall_class, overall_text = "unknown", "❓ Status Unknown"

        branding = _get_branding()
        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3",
                     "accent": branding.get("accent_color", "#3b82f6")}
        css_vars = {k: theme.get(k, v) for k, v in defaults.items()}

        favicon_tag = f'<link rel="icon" href="{branding["favicon_url"]}">' if branding.get("favicon_url") else ""

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page['name']} — Status</title>
{favicon_tag}
<style>{_render_css(css_vars)}
  .ws-indicator {{ display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:0.3rem;vertical-align:middle; }}
  .ws-connected {{ background:#22c55e;box-shadow:0 0 4px #22c55e; }}
  .ws-disconnected {{ background:#ef4444;box-shadow:0 0 4px #ef4444; }}
  .ws-connecting {{ background:#f59e0b;box-shadow:0 0 4px #f59e0b; }}
  .flash-update {{ animation: cardFlash 0.6s ease; }}
  @keyframes cardFlash {{
    0%,100% {{ border-color: rgba(255,255,255,0.04); }}
    50% {{ border-color: #3b82f6; box-shadow: 0 0 12px rgba(59,130,246,0.3); }}
  }}
</style>
</head><body>
<div class="container">
    <header>
        <h1>{branding['header_html']}</h1>
        <p class="tenant" style="font-size:1.1rem;margin-top:0.3rem">{page['name']}</p>
        <p class="tenant">{tenant_name}</p>
    </header>
    <div class="overall-status">
        <span class="badge badge-{overall_class}" id="overall-badge">{overall_text}</span>
    </div>
    <div class="toolbar">
        <div>
            <span class="count-badge" id="count-up">🟢 {up_count} up</span>
            <span class="count-badge" id="count-down">🔴 {down_count} down</span>
            <span class="count-badge">📊 {total} total</span>
        </div>
        <div>
            <span id="ws-status" style="font-size:0.75rem;color:#8b8fa3"><span class="ws-indicator ws-connecting"></span>connecting...</span>
            <a href="/manage" class="btn">🔧 Manage</a>
        </div>
    </div>
    {monitors_html}
    <footer>
        <a href="/incidents" style="color:var(--accent)">🚨 Incident History</a> &middot;
        <a href="/audit" style="color:var(--accent)">📝 Audit Log</a> &middot;
        <a href="/files" style="color:var(--accent)">☁️ Files</a> &middot;
        <a href="/manage" style="color:var(--accent)">🔧 Manage</a><br>
        {branding['footer_html']}<br>
        <span id="ws-footer-status">🔄 Real-time updates via WebSocket</span> &middot; Click a card for details
    </footer>
</div>
<script>
// ── WebSocket Real-Time Updates ──
(function(){{
  var wsUrl = 'ws://' + location.hostname + ':8000/ws/status';
  var ws = null;
  var reconnectDelay = 1000;
  var maxReconnect = 30000;
  var statusEl = document.getElementById('ws-status');
  var footerEl = document.getElementById('ws-footer-status');

  function setWsStatus(state, text){{
    var dot = statusEl.querySelector('.ws-indicator');
    dot.className = 'ws-indicator ws-' + state;
    statusEl.lastChild.textContent = text;
  }}

  function connect(){{
    ws = new WebSocket(wsUrl);
    ws.onopen = function(){{
      reconnectDelay = 1000;
      setWsStatus('connected', 'live');
      footerEl.textContent = '⚡ Real-time updates active';
      // Send pings every 25s to keep alive
      ws._pingInterval = setInterval(function(){{ try{{ ws.send('ping'); }}catch(e){{}} }}, 25000);
    }};
    ws.onclose = function(){{
      clearInterval(ws._pingInterval);
      setWsStatus('disconnected', 'reconnecting...');
      footerEl.textContent = '🔄 Reconnecting...';
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.5, maxReconnect);
    }};
    ws.onerror = function(){{ ws.close(); }};
    ws.onmessage = function(evt){{
      try{{
        var msg = JSON.parse(evt.data);
        if(msg.type === 'status_update') handleStatusUpdate(msg);
      }}catch(e){{}}
    }};
  }}

  function handleStatusUpdate(msg){{
    // Find the card for this monitor
    var card = document.querySelector('[data-monitor-id="'+msg.monitor_id+'"]');
    if(!card) return;

    // Update status dot
    var dot = card.querySelector('.status-dot');
    if(dot){{
      dot.className = 'status-dot dot-' + msg.status;
    }}

    // Update status text
    var stxt = card.querySelector('.status-text');
    if(stxt){{
      stxt.textContent = msg.status === 'up' ? 'Up' : msg.status === 'down' ? 'Down' : msg.status === 'timeout' ? 'Timeout' : msg.status;
    }}

    // Update response time
    var rt = card.querySelector('.response-time');
    if(rt && msg.response_time_ms > 0){{
      rt.textContent = msg.response_time_ms.toFixed(0) + 'ms';
    }}

    // Flash animation
    card.classList.remove('flash-update');
    void card.offsetWidth; // reflow
    card.classList.add('flash-update');

    // Update counters
    updateCounters();
  }}

  function updateCounters(){{
    var cards = document.querySelectorAll('.monitor-card');
    var up = 0, down = 0;
    cards.forEach(function(c){{
      var dot = c.querySelector('.status-dot');
      if(dot){{
        if(dot.classList.contains('dot-up')) up++;
        else if(dot.classList.contains('dot-down') || dot.classList.contains('dot-timeout')) down++;
      }}
    }});
    var countUp = document.getElementById('count-up');
    var countDown = document.getElementById('count-down');
    if(countUp) countUp.textContent = '🟢 ' + up + ' up';
    if(countDown) countDown.textContent = '🔴 ' + down + ' down';

    // Update overall badge
    var badge = document.getElementById('overall-badge');
    if(badge){{
      var total = cards.length;
      if(down === 0 && total > 0){{
        badge.className = 'badge badge-operational';
        badge.textContent = '✅ All ' + total + ' Systems Operational';
      }} else if(down > 0){{
        badge.className = 'badge badge-outage';
        badge.textContent = '🚨 ' + down + ' of ' + total + ' Systems Down';
      }}
    }}
  }}

  connect();

  // Fallback: full page reload every 5 minutes (in case WS stays disconnected)
  setTimeout(function(){{ location.reload(); }}, 300000);
}})();
</script>
</body></html>"""

    # ── Manage Monitors Page ─────────────────────────────────────────────
    @app.get("/manage", response_class=HTMLResponse)
    async def manage_page():
        from windows.local_database import list_tenants, list_monitors, get_recent_results

        tenants = list_tenants()
        all_monitors = []
        for t in tenants:
            monitors = list_monitors(t["id"])
            for m in monitors:
                results = get_recent_results(m["id"], limit=1)
                s = results[0]["status"] if results else "pending"
                m["_status"] = s
                m["_tenant_name"] = t["name"]
                all_monitors.append(m)

        rows = ""
        for m in all_monitors:
            s = m["_status"]
            dot_class = f"dot-{s}"
            click_url = _build_clickable_url(m["target"], m["monitor_type"])
            link = f'<a href="{click_url}" target="_blank">{m["target"]}</a>' if click_url else m["target"]
            grp = m.get("group_name", "") or ""
            grp_badge = f'<span style="background:#222636;padding:2px 8px;border-radius:10px;font-size:0.75rem;color:#8b8fa3">{grp}</span>' if grp else '<span style="color:#555;font-size:0.75rem">—</span>'

            rows += f"""<tr>
                <td><span class="status-dot {dot_class}" style="display:inline-block;vertical-align:middle"></span> {s}</td>
                <td><strong>{m['name']}</strong></td>
                <td><code>{m['monitor_type']}</code></td>
                <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{link}</td>
                <td>{grp_badge}</td>
                <td>{m['interval_seconds']}s</td>
                <td>
                    <a href="/manage/edit/{m['id']}" class="btn" style="padding:0.3rem 0.6rem;font-size:0.8rem">✏️ Edit</a>
                    <a href="/manage/delete/{m['id']}" class="btn btn-danger" style="padding:0.3rem 0.6rem;font-size:0.8rem"
                       onclick="return confirm('Delete {m['name']}?')">🗑️</a>
                </td>
            </tr>"""

        if not rows:
            rows = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:#888">No monitors yet</td></tr>'

        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3", "accent": "#3b82f6"}

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manage Monitors — Tech Sentinel</title>
<style>{_render_css(defaults)}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #333750; }}
  th {{ color: #8b8fa3; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  code {{ background: #222636; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; }}
  .form-card {{ background: var(--bg-card); border-radius: 12px; padding: 1.5rem; margin-top: 1.5rem;
    border: 1px solid #333750; }}
  .form-row {{ display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: end; margin-bottom: 0.75rem; }}
  .form-group {{ display: flex; flex-direction: column; }}
  .form-group label {{ font-size: 0.8rem; color: #8b8fa3; margin-bottom: 0.25rem; }}
  .form-group input, .form-group select {{
    background: #1a1d27; border: 1px solid #333750; border-radius: 6px;
    color: #e1e4ed; padding: 0.5rem 0.7rem; font-size: 0.9rem; min-width: 160px;
  }}
  .form-group input:focus, .form-group select:focus {{ border-color: #3b82f6; outline: none; }}
</style>
</head><body>
<div class="container">
  <header><h1>🔧 Manage Monitors</h1>
    <p class="tenant">{len(all_monitors)} monitors across {len(tenants)} tenant(s)</p>
  </header>

  <div class="toolbar">
    <div><a href="/" class="btn">← Status Pages</a></div>
  </div>

  <div style="overflow-x:auto">
    <table><tr>
        <th>Status</th><th>Name</th><th>Type</th><th>Target</th><th>Group</th><th>Interval</th><th>Actions</th>
    </tr>{rows}</table>
  </div>

  <div class="form-card">
    <h2 style="margin-bottom:1rem;font-size:1.1rem">➕ Add New Monitor</h2>
    <form action="/manage/add" method="post">
      <div class="form-row">
        <div class="form-group"><label>Name</label>
          <input type="text" name="name" required placeholder="My Server"></div>
        <div class="form-group"><label>Type</label>
          <select name="monitor_type">
            <option value="ping">🏓 Ping</option>
            <option value="http">🌐 HTTP</option>
            <option value="tcp">🔌 TCP</option>
            <option value="heartbeat">💓 Heartbeat</option>
          </select></div>
        <div class="form-group"><label>Target</label>
          <input type="text" name="target" required placeholder="192.168.1.1 or http://..."></div>
        <div class="form-group"><label>Group</label>
          <input type="text" name="group_name" placeholder="e.g. 📦 NAS Servers" list="group-list"></div>
        <div class="form-group"><label>Interval (sec)</label>
          <input type="number" name="interval_seconds" value="60" min="10" max="3600"></div>
        <div class="form-group"><label>Timeout (sec)</label>
          <input type="number" name="timeout_seconds" value="10" min="1" max="120"></div>
        <div class="form-group"><label>&nbsp;</label>
          <button type="submit" class="btn btn-primary" style="border:none">➕ Add Monitor</button></div>
      </div>
    </form>
    <datalist id="group-list">
      {"".join(f'<option value="{g}">' for g in sorted(set(m.get("group_name","") for m in all_monitors if m.get("group_name",""))))}
      <option value="🖥️ Agents">
      <option value="📦 NAS Servers">
      <option value="🌐 Web Services">
      <option value="🖨️ Infrastructure">
      <option value="📹 Cameras">
      <option value="🖧 Proxmox">
    </datalist>
  </div>
</div>
</body></html>"""

    # ── Add Monitor (POST) ───────────────────────────────────────────────
    @app.post("/manage/add")
    async def add_monitor(
        name: str = Form(...), monitor_type: str = Form(...),
        target: str = Form(...), interval_seconds: int = Form(60),
        timeout_seconds: int = Form(10), group_name: str = Form(""),
    ):
        from windows.local_database import list_tenants, create_tenant, create_monitor
        from windows.local_queue import enqueue_job

        tenants = list_tenants()
        if not tenants:
            tenant = create_tenant("REGTeches / Bay Area Tech", "regteches")
        else:
            tenant = tenants[0]

        m = create_monitor(
            tenant_id=tenant["id"], name=name, monitor_type=monitor_type,
            target=target, interval_seconds=interval_seconds,
            timeout_seconds=timeout_seconds, group_name=group_name.strip(),
        )
        enqueue_job({
            "monitor_id": m["id"], "tenant_id": m["tenant_id"],
            "monitor_type": m["monitor_type"], "target": m["target"],
            "interval_seconds": str(m["interval_seconds"]),
            "timeout_seconds": str(m["timeout_seconds"]),
            "config": m.get("config", "{}"),
        })

        # Also add to status page if one exists
        _add_monitor_to_status_pages(tenant["id"], m["id"])

        return RedirectResponse("/manage", status_code=303)

    # ── Edit Monitor (GET form) ──────────────────────────────────────────
    @app.get("/manage/edit/{monitor_id}", response_class=HTMLResponse)
    async def edit_monitor_form(monitor_id: str):
        from windows.local_database import get_monitor

        m = get_monitor(monitor_id)
        if not m:
            return HTMLResponse("<h1>Monitor not found</h1>", status_code=404)

        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3", "accent": "#3b82f6"}

        type_options = ""
        for t in ["ping", "http", "tcp", "heartbeat"]:
            sel = "selected" if t == m["monitor_type"] else ""
            icons = {"ping": "🏓", "http": "🌐", "tcp": "🔌", "heartbeat": "💓"}
            type_options += f'<option value="{t}" {sel}>{icons[t]} {t.upper()}</option>'

        status_options = ""
        for s in ["active", "paused"]:
            sel = "selected" if s == m["status"] else ""
            status_options += f'<option value="{s}" {sel}>{s.capitalize()}</option>'

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Edit {m['name']} — Tech Sentinel</title>
<style>{_render_css(defaults)}
  .form-card {{ background: var(--bg-card); border-radius: 12px; padding: 2rem; margin-top: 1rem;
    border: 1px solid #333750; max-width: 600px; margin-left: auto; margin-right: auto; }}
  .form-group {{ margin-bottom: 1rem; }}
  .form-group label {{ display: block; font-size: 0.85rem; color: #8b8fa3; margin-bottom: 0.3rem; }}
  .form-group input, .form-group select {{
    width: 100%; background: #1a1d27; border: 1px solid #333750; border-radius: 6px;
    color: #e1e4ed; padding: 0.6rem 0.8rem; font-size: 0.95rem;
  }}
  .form-group input:focus, .form-group select:focus {{ border-color: #3b82f6; outline: none; }}
  .btn-row {{ display: flex; gap: 0.75rem; margin-top: 1.5rem; }}
</style>
</head><body>
<div class="container">
  <header><h1>✏️ Edit Monitor</h1></header>
  <div class="form-card">
    <form action="/manage/edit/{m['id']}" method="post">
      <div class="form-group"><label>Name</label>
        <input type="text" name="name" value="{m['name']}" required></div>
      <div class="form-group"><label>Type</label>
        <select name="monitor_type">{type_options}</select></div>
      <div class="form-group"><label>Target</label>
        <input type="text" name="target" value="{m['target']}" required></div>
      <div class="form-group"><label>Group</label>
        <input type="text" name="group_name" value="{m.get('group_name','')}" placeholder="e.g. 📦 NAS Servers"
          list="group-list-edit"></div>
      <datalist id="group-list-edit">
        <option value="🖥️ Agents"><option value="📦 NAS Servers"><option value="🌐 Web Services">
        <option value="🖨️ Infrastructure"><option value="📹 Cameras"><option value="🖧 Proxmox">
      </datalist>
      <div class="form-group"><label>Interval (seconds)</label>
        <input type="number" name="interval_seconds" value="{m['interval_seconds']}" min="10" max="3600"></div>
      <div class="form-group"><label>Timeout (seconds)</label>
        <input type="number" name="timeout_seconds" value="{m['timeout_seconds']}" min="1" max="120"></div>
      <div class="form-group"><label>Status</label>
        <select name="status">{status_options}</select></div>
      <div class="btn-row">
        <button type="submit" class="btn btn-primary" style="border:none">💾 Save Changes</button>
        <a href="/manage" class="btn">Cancel</a>
      </div>
    </form>
  </div>
</div>
</body></html>"""

    # ── Edit Monitor (POST save) ─────────────────────────────────────────
    @app.post("/manage/edit/{monitor_id}")
    async def edit_monitor_save(
        monitor_id: str, name: str = Form(...), monitor_type: str = Form(...),
        target: str = Form(...), interval_seconds: int = Form(60),
        timeout_seconds: int = Form(10), status: str = Form("active"),
        group_name: str = Form(""),
    ):
        from windows.local_database import get_monitor, _get_conn, update_monitor_status
        import json as _json
        from datetime import datetime, timezone

        m = get_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")

        conn = _get_conn()
        conn.execute(
            """UPDATE monitors SET name=?, monitor_type=?, target=?,
               interval_seconds=?, timeout_seconds=?, status=?, group_name=?, updated_at=?
               WHERE id=?""",
            (name, monitor_type, target, interval_seconds, timeout_seconds,
             status, group_name.strip(), datetime.now(timezone.utc).isoformat(), monitor_id),
        )
        conn.commit()

        return RedirectResponse("/manage", status_code=303)

    # ── Delete Monitor ───────────────────────────────────────────────────
    @app.get("/manage/delete/{monitor_id}")
    async def delete_monitor_action(monitor_id: str):
        from windows.local_database import get_monitor, delete_monitor

        m = get_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")

        delete_monitor(monitor_id)
        return RedirectResponse("/manage", status_code=303)

    # ── Monitor Detail Page (charts, uptime, history) ────────────────────
    @app.get("/monitor/{monitor_id}", response_class=HTMLResponse)
    async def monitor_detail(monitor_id: str):
        from windows.local_database import (
            get_monitor, get_uptime_stats, get_response_time_series,
            get_recent_results, get_incidents, get_avg_response_time,
            is_in_maintenance, get_performance_history,
            get_command_history,
        )

        m = get_monitor(monitor_id)
        if not m:
            return HTMLResponse("<h1>Monitor not found</h1>", status_code=404)

        stats = get_uptime_stats(monitor_id)
        series = get_response_time_series(monitor_id, 60)
        recent = get_recent_results(monitor_id, 20)
        incidents = get_incidents(monitor_id, 10)
        avg_ms = get_avg_response_time(monitor_id, 24)
        mw = is_in_maintenance(monitor_id)

        # Current status
        cur_status = recent[0]["status"] if recent else "pending"
        if mw:
            cur_status = "maintenance"

        # Build SVG chart (larger sparkline)
        chart_svg = _build_sparkline_svg(series, width=600, height=80) if series else "<p style='color:#888'>No data yet</p>"

        # Recent checks table
        checks_rows = ""
        for r in recent:
            s = r["status"]
            dot = f'<span class="status-dot dot-{s}" style="display:inline-block;vertical-align:middle"></span>'
            ms = f'{r.get("response_time_ms", 0):.0f}ms' if r.get("response_time_ms") else "-"
            err = r.get("error", "") or ""
            ts = r.get("checked_at", "")[:19]
            checks_rows += f"<tr><td>{dot} {s}</td><td>{ms}</td><td class='ts'>{ts}</td><td style='color:#888;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{err}</td></tr>"

        # Incidents table
        inc_rows = ""
        for inc in incidents:
            event_icon = "🚨" if inc["event"] == "down" else "✅"
            duration = ""
            if inc.get("duration_sec"):
                mins = inc["duration_sec"] / 60
                duration = f"{mins:.0f}m" if mins < 60 else f"{mins/60:.1f}h"
            resolved = inc.get("resolved_at", "")[:19] if inc.get("resolved_at") else "Ongoing"
            inc_rows += f"<tr><td>{event_icon} {inc['event']}</td><td class='ts'>{inc.get('started_at','')[:19]}</td><td class='ts'>{resolved}</td><td>{duration}</td><td style='color:#888'>{inc.get('error','')[:60]}</td></tr>"

        if not inc_rows:
            inc_rows = '<tr><td colspan="5" style="text-align:center;color:#888;padding:1rem">No incidents recorded</td></tr>'

        # SSL info
        ssl_info = ""
        if m.get("ssl_expiry"):
            try:
                from datetime import datetime as dt
                days_left = (dt.fromisoformat(m["ssl_expiry"]) - dt.now()).days
                color = "#22c55e" if days_left > 30 else "#f59e0b" if days_left > 14 else "#ef4444"
                ssl_info = f'<div style="margin-top:0.5rem"><span style="color:{color}">🔐 SSL expires in {days_left} days ({m["ssl_expiry"][:10]})</span></div>'
            except Exception:
                pass

        # Maintenance info
        maint_info = ""
        if mw:
            maint_info = f'<div style="background:rgba(107,114,128,0.15);color:#9ca3af;padding:0.75rem;border-radius:8px;margin:0.75rem 0">🔧 In maintenance until {mw.get("end_time","")} — {mw.get("reason","")}</div>'

        type_icons = {"http": "🌐", "tcp": "🔌", "ping": "📡", "heartbeat": "💓"}
        icon = type_icons.get(m["monitor_type"], "📍")

        # System info card for heartbeat/agent monitors
        sysinfo_html = ""
        if m["monitor_type"] == "heartbeat" and m.get("config"):
            try:
                cfg = m["config"]
                if isinstance(cfg, str):
                    cfg = json.loads(cfg)
                if isinstance(cfg, dict) and cfg.get("hostname"):
                    si = cfg
                    # Build system info card
                    ram = si.get("ram", {})
                    cpu = si.get("cpu", {})
                    uptime_info = si.get("uptime", {})
                    os_info = si.get("os", {})
                    disks = si.get("disks", [])
                    gpu_list = si.get("gpu", [])
                    load = si.get("load_average", {})

                    disk_rows = ""
                    for d in disks:
                        drive = d.get("drive", d.get("mount", "?"))
                        pct = d.get("percent_used", 0)
                        bar_color = "#22c55e" if pct < 80 else "#f59e0b" if pct < 95 else "#ef4444"
                        disk_rows += (
                            f'<tr><td>{drive}</td>'
                            f'<td>{d.get("total_gb", "?")} GB</td>'
                            f'<td>{d.get("used_gb", "?")} GB</td>'
                            f'<td>{d.get("free_gb", "?")} GB</td>'
                            f'<td><div style="background:#333;border-radius:4px;height:12px;width:100px;display:inline-block;vertical-align:middle">'
                            f'<div style="background:{bar_color};height:100%;border-radius:4px;width:{pct}%"></div></div> {pct}%</td></tr>'
                        )

                    gpu_text = ", ".join(g.get("name", "?") for g in gpu_list) if gpu_list else "N/A"
                    load_text = f'{load.get("1min","?")} / {load.get("5min","?")} / {load.get("15min","?")}' if load else ""

                    sysinfo_html = f"""
                    <div class="detail-card">
                      <h3 style="margin:0 0 0.75rem;font-size:1rem">💻 System Information</h3>
                      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem 2rem;font-size:0.9rem">
                        <div><span style="color:var(--text-secondary)">Hostname:</span> <strong>{si.get('hostname','?')}</strong></div>
                        <div><span style="color:var(--text-secondary)">IP:</span> {si.get('local_ip','?')}</div>
                        <div><span style="color:var(--text-secondary)">OS:</span> {os_info.get('distro','') or os_info.get('edition','?')}</div>
                        <div><span style="color:var(--text-secondary)">Agent:</span> {si.get('agent_type','?')} v{si.get('agent_version','?')}</div>
                        <div><span style="color:var(--text-secondary)">CPU:</span> {cpu.get('name','?')} ({cpu.get('cores_logical','?')} cores)</div>
                        <div><span style="color:var(--text-secondary)">CPU Usage:</span> {cpu.get('usage_percent','?')}%</div>
                        <div><span style="color:var(--text-secondary)">RAM:</span> {ram.get('used_gb','?')}/{ram.get('total_gb','?')} GB ({ram.get('percent_used','?')}%)</div>
                        <div><span style="color:var(--text-secondary)">Uptime:</span> {uptime_info.get('uptime_human','?')}</div>
                        <div><span style="color:var(--text-secondary)">GPU:</span> {gpu_text}</div>
                        <div><span style="color:var(--text-secondary)">Python:</span> {si.get('python_version','?')[:20]}</div>
                        {"<div><span style='color:var(--text-secondary)'>Load:</span> " + load_text + "</div>" if load_text else ""}
                        <div><span style="color:var(--text-secondary)">Last Report:</span> {si.get('collected_at','?')[:19]}</div>
                      </div>
                      {"<h4 style='margin:1rem 0 0.5rem;font-size:0.9rem'>💾 Disk Usage</h4><table><tr><th>Drive</th><th>Total</th><th>Used</th><th>Free</th><th>Usage</th></tr>" + disk_rows + "</table>" if disk_rows else ""}
                    </div>"""
            except Exception:
                pass

        # ── Performance Charts (agent monitors only) ──────────────────
        perf_html = ""
        if m["monitor_type"] == "heartbeat":
            perf_data = get_performance_history(monitor_id, limit=60)
            if perf_data:
                def _perf_chart(data_points, key, color, label):
                    vals = [p.get(key) or 0 for p in data_points]
                    if not any(vals):
                        return ""
                    width, height = 600, 60
                    n = len(vals)
                    max_v = 100  # percentage scale
                    pts = []
                    for i, v in enumerate(vals):
                        x = (i / max(n - 1, 1)) * width
                        y = height - (v / max_v) * (height - 4)
                        pts.append(f"{x:.1f},{y:.1f}")
                    poly = " ".join(pts)
                    fill_pts = f"0,{height} " + poly + f" {width},{height}"
                    cur = vals[-1] if vals else 0
                    return (
                        f'<div style="margin-bottom:0.75rem">'
                        f'<div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:2px">'
                        f'<span style="color:var(--text-secondary)">{label}</span>'
                        f'<span style="color:{color};font-weight:600">{cur:.1f}%</span></div>'
                        f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:{height}px;border-radius:6px;background:#1a1d27">'
                        f'<polygon points="{fill_pts}" fill="{color}" fill-opacity="0.15"/>'
                        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
                        f'</svg></div>'
                    )

                cpu_chart = _perf_chart(perf_data, "cpu_percent", "#3b82f6", "🔵 CPU Usage")
                ram_chart = _perf_chart(perf_data, "ram_percent", "#a855f7", "🟣 RAM Usage")
                disk_chart = _perf_chart(perf_data, "disk_percent", "#f59e0b", "🟡 Disk Usage (max)")

                if cpu_chart or ram_chart or disk_chart:
                    perf_html = f"""
                    <div class="detail-card">
                      <h3 style="margin:0 0 0.75rem;font-size:1rem">📊 Performance Trends (last {len(perf_data)} samples)</h3>
                      {cpu_chart}{ram_chart}{disk_chart}
                    </div>"""

        # ── IT Tools Panel (all 6 features in one tabbed card) ─────────
        rdp_html = ""
        remote_cmd_html = ""
        it_tools_html = ""
        if m["monitor_type"] == "heartbeat":
            agent_ip = ""
            agent_hostname = ""
            agent_type = ""
            try:
                _cfg = m.get("config", "{}")
                if isinstance(_cfg, str):
                    _cfg = json.loads(_cfg)
                agent_ip = _cfg.get("local_ip", "")
                agent_hostname = _cfg.get("hostname", "")
                agent_type = _cfg.get("agent_type", "")
            except Exception:
                pass

            cmd_history = get_command_history(monitor_id, limit=20)
            cmd_rows = ""
            for cmd in cmd_history:
                cmd_st = cmd.get("status", "?")
                st_icons = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}
                status_icon = st_icons.get(cmd_st, "❓")
                output_preview = (cmd.get("output") or "")[:80]
                if len(cmd.get("output") or "") > 80:
                    output_preview += "..."
                exit_code = cmd.get("exit_code", "")
                exit_display = f' (exit {exit_code})' if exit_code is not None and cmd_st == "completed" else ""
                cmd_rows += (
                    f"<tr>"
                    f"<td>{status_icon} {cmd_st}{exit_display}</td>"
                    f"<td><code style='font-size:0.8rem'>{cmd.get('command','')[:60]}</code></td>"
                    f"<td class='ts'>{(cmd.get('created_at') or '')[:19]}</td>"
                    f"<td style='color:#888;font-size:0.8rem;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer' "
                    f"onclick=\"this.style.whiteSpace=this.style.whiteSpace==='pre-wrap'?'nowrap':'pre-wrap'\">{output_preview}</td>"
                    f"</tr>"
                )
            if not cmd_rows:
                cmd_rows = '<tr><td colspan="4" style="text-align:center;color:#888;padding:1rem">No commands sent yet</td></tr>'

            ssh_hint = f' &middot; <code>ssh {agent_ip}</code>' if agent_type == "linux" else ""
            connect_btns = ""
            if agent_ip and agent_ip != "unknown":
                connect_btns = f"""
                <a href="/rdp/{monitor_id}" class="tbtn" style="background:#3b82f6">🖥️ RDP ({agent_ip})</a>
                <a href="/vnc/{monitor_id}" class="tbtn" style="background:#8b5cf6">🔗 VNC</a>
                <button onclick="sendWoL()" class="tbtn" style="background:#22c55e">⚡ Wake-on-LAN</button>
                <span style="color:var(--text-secondary);font-size:0.8rem">{agent_hostname}{ssh_hint}</span>"""

            it_tools_html = f"""
            <div class="detail-card">
              <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem;border-bottom:1px solid #333750;padding-bottom:0.75rem">
                <button class="tab-btn active" onclick="showTab('connect')">🖥️ Connect</button>
                <button class="tab-btn" onclick="showTab('terminal')">🔧 Terminal</button>
                <button class="tab-btn" onclick="showTab('services')">⚙️ Services</button>
                <button class="tab-btn" onclick="showTab('processes')">📊 Processes</button>
                <button class="tab-btn" onclick="showTab('software')">📦 Software</button>
                <button class="tab-btn" onclick="showTab('eventlog')">📋 Event Log</button>
                <button class="tab-btn" onclick="showTab('files')">📁 Files</button>
                <button class="tab-btn" onclick="showTab('messages')">💬 Message</button>
              </div>

              <!-- Connect Tab -->
              <div id="tab-connect" class="tab-panel active">
                <div style="display:flex;gap:0.75rem;flex-wrap:wrap;align-items:center">
                  {connect_btns}
                </div>
                <div id="wol-msg" style="display:none;margin-top:0.5rem;padding:0.5rem;border-radius:6px;font-size:0.85rem"></div>
              </div>

              <!-- Terminal Tab -->
              <div id="tab-terminal" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem">
                  <input type="text" id="cmd-input" placeholder="Enter command..." style="flex:1;padding:0.5rem 0.75rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-family:monospace;font-size:0.85rem"
                    onkeydown="if(event.key==='Enter')sendCommand()">
                  <button onclick="sendCommand()" id="run-btn" class="tbtn" style="background:#3b82f6">▶ Run</button>
                </div>
                <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.75rem">
                  <button onclick="quickCmd('systeminfo')" class="qcmd">📋 systeminfo</button>
                  <button onclick="quickCmd('ipconfig /all')" class="qcmd">🌐 ipconfig</button>
                  <button onclick="quickCmd('tasklist')" class="qcmd">📊 tasklist</button>
                  <button onclick="quickCmd('net user')" class="qcmd">👥 net user</button>
                  <button onclick="quickCmd('netstat -an')" class="qcmd">🔌 netstat</button>
                  <button onclick="quickCmd('hostname')" class="qcmd">🏷️ hostname</button>
                </div>
                <div id="cmd-output" style="display:none;background:#0d1117;border:1px solid #333750;border-radius:8px;padding:1rem;margin-bottom:1rem;max-height:400px;overflow:auto">
                  <div style="display:flex;justify-content:space-between;margin-bottom:0.5rem">
                    <span id="cmd-status-label" style="color:#3b82f6;font-size:0.8rem">⏳ Waiting...</span>
                    <button onclick="document.getElementById('cmd-output').style.display='none'" style="background:none;border:none;color:#888;cursor:pointer;font-size:0.8rem">✕ Close</button>
                  </div>
                  <pre id="cmd-output-text" style="margin:0;font-size:0.8rem;color:#e1e4ed;white-space:pre-wrap;word-break:break-all"></pre>
                </div>
                <div style="overflow-x:auto"><table>
                  <tr><th>Status</th><th>Command</th><th>Time</th><th>Output</th></tr>
                  {cmd_rows}
                </table></div>
              </div>

              <!-- Services Tab -->
              <div id="tab-services" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;align-items:center">
                  <button onclick="loadServices()" class="tbtn" style="background:#3b82f6">🔄 Load Services</button>
                  <input type="text" id="svc-filter" placeholder="Filter services..." oninput="filterTable('svc-table',this.value)" style="flex:1;padding:0.4rem 0.75rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-size:0.85rem">
                </div>
                <div id="svc-output" style="overflow-x:auto"><p style="color:#888">Click "Load Services" to fetch from agent</p></div>
              </div>

              <!-- Processes Tab -->
              <div id="tab-processes" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;align-items:center">
                  <button onclick="loadProcesses()" class="tbtn" style="background:#3b82f6">🔄 Load Processes</button>
                  <input type="text" id="proc-filter" placeholder="Filter processes..." oninput="filterTable('proc-table',this.value)" style="flex:1;padding:0.4rem 0.75rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-size:0.85rem">
                </div>
                <div id="proc-output" style="overflow-x:auto"><p style="color:#888">Click "Load Processes" to fetch from agent</p></div>
              </div>

              <!-- Software Tab -->
              <div id="tab-software" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;align-items:center">
                  <button onclick="loadSoftware()" class="tbtn" style="background:#3b82f6">🔄 Load Software</button>
                  <input type="text" id="sw-filter" placeholder="Filter software..." oninput="filterTable('sw-table',this.value)" style="flex:1;padding:0.4rem 0.75rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-size:0.85rem">
                </div>
                <div id="sw-output" style="overflow-x:auto"><p style="color:#888">Click "Load Software" to fetch from agent</p></div>
              </div>

              <!-- Event Log Tab -->
              <div id="tab-eventlog" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem">
                  <button onclick="loadEventLog()" class="tbtn" style="background:#3b82f6">🔄 Load Event Log</button>
                </div>
                <div id="evtlog-output" style="overflow-x:auto"><p style="color:#888">Click "Load Event Log" to fetch from agent</p></div>
              </div>

              <!-- Files Tab -->
              <div id="tab-files" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;align-items:center">
                  <button onclick="browseTo(currentPath?currentPath.split('/').slice(0,-1).join('/'):'')" class="tbtn" style="background:#555">⬆ Up</button>
                  <input type="text" id="path-input" placeholder="C:\\\\ or /home" value="C:\\\\" style="flex:1;padding:0.4rem 0.75rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-family:monospace;font-size:0.85rem"
                    onkeydown="if(event.key==='Enter')browseTo(this.value)">
                  <button onclick="browseTo(document.getElementById('path-input').value)" class="tbtn" style="background:#3b82f6">📂 Browse</button>
                </div>
                <div id="files-output" style="overflow-x:auto"><p style="color:#888">Enter a path and click "Browse"</p></div>
              </div>

              <!-- Messages Tab -->
              <div id="tab-messages" class="tab-panel">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem">
                  <select id="msg-type" style="padding:0.4rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-size:0.85rem">
                    <option value="info">💬 Info</option>
                    <option value="warning">⚠️ Warning</option>
                    <option value="alert">🚨 Alert (popup)</option>
                  </select>
                  <input type="text" id="msg-input" placeholder="Type a message to send to the remote user..." style="flex:1;padding:0.4rem 0.75rem;border-radius:6px;border:1px solid #333750;background:#1a1d27;color:#e1e4ed;font-size:0.85rem"
                    onkeydown="if(event.key==='Enter')sendMessage()">
                  <button onclick="sendMessage()" class="tbtn" style="background:#3b82f6">📤 Send</button>
                </div>
                <div id="msg-status" style="display:none;padding:0.5rem;border-radius:6px;margin-bottom:0.75rem;font-size:0.85rem"></div>
                <p style="color:#888;font-size:0.8rem;margin:0 0 0.75rem">💬 Info = console only &middot; ⚠️ Warning = desktop notification &middot; 🚨 Alert = popup dialog on remote PC</p>
                <div id="msg-history"><p style="color:#888">No messages sent yet</p></div>
              </div>
            </div>"""

        branding = _get_branding()
        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3",
                     "accent": branding.get("accent_color", "#3b82f6")}

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{m['name']} — Monitor Detail</title>
<style>{_render_css(defaults)}
  .ws-indicator {{ display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:0.3rem;vertical-align:middle; }}
  .ws-connected {{ background:#22c55e;box-shadow:0 0 4px #22c55e; }}
  .ws-disconnected {{ background:#ef4444;box-shadow:0 0 4px #ef4444; }}
  .ws-connecting {{ background:#f59e0b;box-shadow:0 0 4px #f59e0b; }}
  .detail-card {{ background: var(--bg-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; border: 1px solid rgba(255,255,255,0.04); }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin-bottom: 1rem; }}
  @media (max-width: 700px) {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  .stat-box {{ background: var(--bg-secondary); border-radius: 10px; padding: 1rem; text-align: center; }}
  .stat-val {{ font-size: 1.5rem; font-weight: 700; color: var(--accent); }}
  .stat-label {{ font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #333750; font-size: 0.85rem; }}
  th {{ color: #8b8fa3; font-size: 0.75rem; text-transform: uppercase; }}
  .chart-area {{ background: var(--bg-secondary); border-radius: 10px; padding: 1rem; margin-bottom: 1rem; text-align: center; }}
  .qcmd {{ background:#222636;color:#8b8fa3;border:1px solid #333750;padding:0.3rem 0.7rem;border-radius:6px;cursor:pointer;font-size:0.78rem; }}
  .qcmd:hover {{ border-color:#3b82f6;color:#e1e4ed; }}
  .tab-btn {{ background:none;color:#8b8fa3;border:none;padding:0.4rem 0.8rem;cursor:pointer;font-size:0.85rem;border-radius:6px; }}
  .tab-btn:hover {{ color:#e1e4ed;background:#1a1d27; }}
  .tab-btn.active {{ color:#3b82f6;background:#1a1d27;font-weight:600; }}
  .tab-panel {{ display:none; }}
  .tab-panel.active {{ display:block; }}
  .tbtn {{ color:#fff;border:none;padding:0.5rem 1rem;border-radius:6px;cursor:pointer;font-weight:600;font-size:0.85rem;text-decoration:none;display:inline-flex;align-items:center;gap:0.3rem; }}
  .tbtn:hover {{ opacity:0.9; }}
  .svc-running {{ color:#22c55e; }} .svc-stopped {{ color:#ef4444; }} .svc-other {{ color:#f59e0b; }}
</style>
</head><body>
<div class="container">
  <div style="margin-bottom:1rem"><a href="javascript:history.back()" class="btn" style="font-size:0.8rem">&larr; Back</a></div>

  <div class="detail-card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap">
      <div>
        <h1 style="font-size:1.4rem;margin:0">{icon} {m['name']}</h1>
        <p style="color:var(--text-secondary);margin:0.25rem 0">{m['monitor_type'].upper()} &middot; {m['target']}</p>
        {ssl_info}
      </div>
      <div class="status-badge" style="font-size:1.1rem">
        <span class="status-dot dot-{cur_status}" style="width:12px;height:12px"></span> {cur_status.upper()}
      </div>
    </div>
    {maint_info}
  </div>

  <div class="stat-grid">
    <div class="stat-box"><div class="stat-val">{stats['uptime_24h']:.2f}%</div><div class="stat-label">Uptime 24h</div></div>
    <div class="stat-box"><div class="stat-val">{stats['uptime_7d']:.2f}%</div><div class="stat-label">Uptime 7d</div></div>
    <div class="stat-box"><div class="stat-val">{stats['uptime_30d']:.2f}%</div><div class="stat-label">Uptime 30d</div></div>
    <div class="stat-box"><div class="stat-val">{f"{avg_ms:.0f}ms" if avg_ms else "N/A"}</div><div class="stat-label">Avg Response</div></div>
  </div>

  <div class="chart-area">
    <h3 style="margin:0 0 0.5rem;font-size:0.9rem;color:var(--text-secondary)">📈 Response Time (last {len(series)} checks)</h3>
    {chart_svg}
  </div>

  <div class="detail-card">
    <h3 style="margin:0 0 0.75rem;font-size:1rem">📋 Recent Checks</h3>
    <div style="overflow-x:auto"><table>
      <tr><th>Status</th><th>Response</th><th>Time</th><th>Error</th></tr>
      {checks_rows}
    </table></div>
  </div>

  {sysinfo_html}

  {perf_html}

  {it_tools_html}

  <div class="detail-card">
    <h3 style="margin:0 0 0.75rem;font-size:1rem">🚨 Incident History</h3>
    <div style="overflow-x:auto"><table>
      <tr><th>Event</th><th>Started</th><th>Resolved</th><th>Duration</th><th>Error</th></tr>
      {inc_rows}
    </table></div>
  </div>

  <footer>
    <span id="ws-status" style="font-size:0.75rem;color:#8b8fa3"><span class="ws-indicator ws-connecting"></span>connecting...</span><br>
    {branding['footer_html']}
  </footer>
</div>
<script>
// Convert UTC timestamps to local time
document.querySelectorAll('.ts').forEach(function(el){{
  var raw = el.textContent.trim();
  if(!raw || raw==='Ongoing') return;
  try{{
    var d = new Date(raw.replace(' ','T')+'Z');
    if(isNaN(d)) return;
    el.textContent = d.toLocaleString(undefined, {{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true}});
    el.title = raw + ' UTC';
  }}catch(e){{}}
}});

var apiBase = 'http://' + location.hostname + ':8000';
var monitorId = '{monitor_id}';
var pollTimer = null;
var _apiKey = null;
var currentPath = 'C:\\\\';

function getApiKey(){{
  if(_apiKey) return Promise.resolve(_apiKey);
  return fetch(apiBase+'/api/v1/tenants/').then(function(r){{return r.json()}}).then(function(t){{
    if(!t.length) throw new Error('No tenants');
    _apiKey=t[0].api_key; return _apiKey;
  }});
}}

// ── Tab Switching ──
function showTab(name){{
  document.querySelectorAll('.tab-panel').forEach(function(p){{p.classList.remove('active')}});
  document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.remove('active')}});
  var panel = document.getElementById('tab-'+name);
  if(panel) panel.classList.add('active');
  event.target.classList.add('active');
}}

// ── Send Structured Command & Wait for JSON Result ──
function sendStructured(cmd, callback){{
  getApiKey().then(function(key){{
    return fetch(apiBase+'/api/v1/monitors/'+monitorId+'/commands',{{
      method:'POST', headers:{{'Content-Type':'application/json','X-TS-API-Key':key}},
      body:JSON.stringify({{command:cmd}})
    }});
  }}).then(function(r){{return r.json()}}).then(function(data){{
    var cmdId=data.id, polls=0;
    var iv=setInterval(function(){{
      polls++;
      fetch(apiBase+'/api/v1/monitors/'+monitorId+'/commands?limit=5').then(function(r){{return r.json()}}).then(function(cmds){{
        var f=cmds.find(function(c){{return c.id===cmdId}});
        if(f && (f.status==='completed'||f.status==='failed')){{
          clearInterval(iv);
          try{{ var parsed=JSON.parse(f.output); callback(null,parsed); }}
          catch(e){{ callback(null,{{raw:f.output}}); }}
        }}
        if(polls>60){{ clearInterval(iv); callback('Timeout — agent may be offline'); }}
      }});
    }},2000);
  }}).catch(function(e){{ callback(e.message); }});
}}

function filterTable(id,q){{
  var tbl=document.getElementById(id); if(!tbl) return;
  var rows=tbl.querySelectorAll('tbody tr');
  q=q.toLowerCase();
  rows.forEach(function(r){{ r.style.display=r.textContent.toLowerCase().includes(q)?'':'none'; }});
}}

function fmtSize(bytes){{
  if(bytes>1073741824) return (bytes/1073741824).toFixed(1)+' GB';
  if(bytes>1048576) return (bytes/1048576).toFixed(1)+' MB';
  if(bytes>1024) return (bytes/1024).toFixed(1)+' KB';
  return bytes+' B';
}}

// ── Terminal / Commands ──
function quickCmd(cmd){{ document.getElementById('cmd-input').value=cmd; sendCommand(); }}
function sendCommand(){{
  var input=document.getElementById('cmd-input'), cmd=input.value.trim();
  if(!cmd) return;
  var btn=document.getElementById('run-btn');
  btn.disabled=true; btn.textContent='⏳...';
  var outDiv=document.getElementById('cmd-output'), outText=document.getElementById('cmd-output-text');
  var label=document.getElementById('cmd-status-label');
  outDiv.style.display='block'; outText.textContent=''; label.textContent='⏳ Sending...'; label.style.color='#3b82f6';
  getApiKey().then(function(key){{
    return fetch(apiBase+'/api/v1/monitors/'+monitorId+'/commands',{{
      method:'POST',headers:{{'Content-Type':'application/json','X-TS-API-Key':key}},
      body:JSON.stringify({{command:cmd}})
    }});
  }}).then(function(r){{return r.json()}}).then(function(data){{
    label.textContent='⏳ Waiting for agent...'; input.value=''; btn.disabled=false; btn.textContent='▶ Run';
    var cmdId=data.id, polls=0;
    if(pollTimer) clearInterval(pollTimer);
    pollTimer=setInterval(function(){{
      polls++;
      fetch(apiBase+'/api/v1/monitors/'+monitorId+'/commands?limit=5').then(function(r){{return r.json()}}).then(function(cmds){{
        var f=cmds.find(function(c){{return c.id===cmdId}});
        if(f&&f.status==='completed'){{ clearInterval(pollTimer); label.textContent='✅ Done (exit '+f.exit_code+')'; label.style.color=f.exit_code===0?'#22c55e':'#ef4444'; outText.textContent=f.output||'(no output)'; }}
        else if(f&&f.status==='running'){{ label.textContent='🔄 Running...'; }}
        else if(f&&f.status==='failed'){{ clearInterval(pollTimer); label.textContent='❌ Failed'; label.style.color='#ef4444'; outText.textContent=f.output||'(no output)'; }}
        if(polls>60){{ clearInterval(pollTimer); label.textContent='⚠️ Timeout'; }}
      }});
    }},2000);
  }}).catch(function(e){{ label.textContent='❌ '+e.message; label.style.color='#ef4444'; btn.disabled=false; btn.textContent='▶ Run'; }});
}}

// ── Wake-on-LAN ──
function sendWoL(){{
  var msg=document.getElementById('wol-msg');
  msg.style.display='block'; msg.style.background='rgba(59,130,246,0.15)'; msg.style.color='#3b82f6';
  msg.textContent='⏳ Sending Wake-on-LAN...';
  getApiKey().then(function(key){{
    return fetch(apiBase+'/api/v1/monitors/'+monitorId+'/wol',{{
      method:'POST',headers:{{'X-TS-API-Key':key}}
    }});
  }}).then(function(r){{return r.json()}}).then(function(data){{
    if(data.status==='ok'){{ msg.style.background='rgba(34,197,94,0.15)'; msg.style.color='#22c55e'; msg.textContent='✅ '+data.message; }}
    else{{ msg.style.background='rgba(239,68,68,0.15)'; msg.style.color='#ef4444'; msg.textContent='❌ '+(data.detail||'Failed'); }}
  }}).catch(function(e){{ msg.style.background='rgba(239,68,68,0.15)'; msg.style.color='#ef4444'; msg.textContent='❌ '+e.message; }});
}}

// ── Services ──
function loadServices(){{
  document.getElementById('svc-output').innerHTML='<p style="color:#3b82f6">⏳ Loading services from agent...</p>';
  sendStructured('__ts:services',function(err,data){{
    if(err){{ document.getElementById('svc-output').innerHTML='<p style="color:#ef4444">❌ '+err+'</p>'; return; }}
    if(data.error){{ document.getElementById('svc-output').innerHTML='<p style="color:#ef4444">❌ '+data.error+'</p>'; return; }}
    var svcs=data.services||[];
    var h='<p style="color:#888;font-size:0.8rem">'+svcs.length+' services found</p>';
    h+='<table id="svc-table"><thead><tr><th>Status</th><th>Name</th><th>Display Name</th><th>Action</th></tr></thead><tbody>';
    svcs.forEach(function(s){{
      var st=s.status||'unknown';
      var cls=st==='running'?'svc-running':st==='stopped'?'svc-stopped':'svc-other';
      var icon=st==='running'?'🟢':st==='stopped'?'🔴':'🟡';
      var btns='';
      if(st==='running') btns='<button onclick="svcAction(\\'stop\\',\\''+s.name+'\\')\" class="qcmd">⏹ Stop</button> <button onclick="svcAction(\\'restart\\',\\''+s.name+'\\')\" class="qcmd">🔄 Restart</button>';
      else if(st==='stopped'||st==='dead') btns='<button onclick="svcAction(\\'start\\',\\''+s.name+'\\')\" class="qcmd">▶ Start</button>';
      h+='<tr><td class="'+cls+'">'+icon+' '+st+'</td><td><code>'+s.name+'</code></td><td>'+(s.display_name||'')+'</td><td>'+btns+'</td></tr>';
    }});
    h+='</tbody></table>';
    document.getElementById('svc-output').innerHTML=h;
  }});
}}
function svcAction(action,name){{
  if(!confirm(action.toUpperCase()+' service "'+name+'"?')) return;
  sendStructured('__ts:service:'+action+':'+name,function(err,data){{
    if(err) alert('Error: '+err);
    else if(data.error) alert('Error: '+data.error);
    else{{ alert(data.message||'Done'); loadServices(); }}
  }});
}}

// ── Processes ──
function loadProcesses(){{
  document.getElementById('proc-output').innerHTML='<p style="color:#3b82f6">⏳ Loading processes from agent...</p>';
  sendStructured('__ts:processes',function(err,data){{
    if(err){{ document.getElementById('proc-output').innerHTML='<p style="color:#ef4444">❌ '+err+'</p>'; return; }}
    if(data.error){{ document.getElementById('proc-output').innerHTML='<p style="color:#ef4444">❌ '+data.error+'</p>'; return; }}
    var procs=data.processes||[];
    var h='<p style="color:#888;font-size:0.8rem">'+procs.length+' processes (top by memory) — Total: '+(data.total||procs.length)+'</p>';
    h+='<table id="proc-table"><thead><tr><th>PID</th><th>Name</th><th>CPU%</th><th>Memory</th><th>User</th><th>Action</th></tr></thead><tbody>';
    procs.forEach(function(p){{
      var memColor=p.memory_mb>500?'#ef4444':p.memory_mb>100?'#f59e0b':'#e1e4ed';
      h+='<tr><td>'+p.pid+'</td><td>'+p.name+'</td><td>'+p.cpu_percent+'%</td><td style="color:'+memColor+'">'+p.memory_mb+' MB</td><td style="color:#888">'+((p.username||'').split('\\\\').pop())+'</td>';
      h+='<td><button onclick="killProc('+p.pid+',\\''+p.name.replace(/'/g,"")+'\\')\" class="qcmd" style="color:#ef4444;border-color:#ef4444">💀 Kill</button></td></tr>';
    }});
    h+='</tbody></table>';
    document.getElementById('proc-output').innerHTML=h;
  }});
}}
function killProc(pid,name){{
  if(!confirm('Kill process "'+name+'" (PID '+pid+')?')) return;
  sendStructured('__ts:kill:'+pid,function(err,data){{
    if(err) alert('Error: '+err);
    else if(data.error) alert('Error: '+data.error);
    else{{ alert(data.message||'Done'); loadProcesses(); }}
  }});
}}

// ── Software ──
function loadSoftware(){{
  document.getElementById('sw-output').innerHTML='<p style="color:#3b82f6">⏳ Loading installed software from agent...</p>';
  sendStructured('__ts:software',function(err,data){{
    if(err){{ document.getElementById('sw-output').innerHTML='<p style="color:#ef4444">❌ '+err+'</p>'; return; }}
    if(data.error){{ document.getElementById('sw-output').innerHTML='<p style="color:#ef4444">❌ '+data.error+'</p>'; return; }}
    var sw=data.software||[];
    var h='<p style="color:#888;font-size:0.8rem">'+sw.length+' packages installed</p>';
    h+='<table id="sw-table"><thead><tr><th>Name</th><th>Version</th><th>Publisher</th><th>Size</th></tr></thead><tbody>';
    sw.forEach(function(s){{
      h+='<tr><td>'+s.name+'</td><td><code>'+(s.version||'')+'</code></td><td style="color:#888">'+(s.publisher||'')+'</td><td style="color:#888">'+(s.size||'')+'</td></tr>';
    }});
    h+='</tbody></table>';
    document.getElementById('sw-output').innerHTML=h;
  }});
}}

// ── Event Log ──
function loadEventLog(){{
  document.getElementById('evtlog-output').innerHTML='<p style="color:#3b82f6">⏳ Loading event log from agent...</p>';
  sendStructured('__ts:eventlog',function(err,data){{
    if(err){{ document.getElementById('evtlog-output').innerHTML='<p style="color:#ef4444">❌ '+err+'</p>'; return; }}
    if(data.error){{ document.getElementById('evtlog-output').innerHTML='<p style="color:#ef4444">❌ '+data.error+'</p>'; return; }}
    var evts=data.events||[];
    var h='<p style="color:#888;font-size:0.8rem">'+evts.length+' entries</p>';
    h+='<table><thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Message</th></tr></thead><tbody>';
    evts.forEach(function(e){{
      var lc=e.level==='Error'?'#ef4444':e.level==='Warning'?'#f59e0b':'#888';
      var icon=e.level==='Error'?'🔴':e.level==='Warning'?'🟡':'🔵';
      h+='<tr><td style="white-space:nowrap">'+e.time+'</td><td style="color:'+lc+'">'+icon+' '+e.level+'</td><td>'+e.source+'</td><td style="color:#888;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+e.message+'</td></tr>';
    }});
    h+='</tbody></table>';
    document.getElementById('evtlog-output').innerHTML=h;
  }});
}}

// ── File Browser ──
function browseTo(path){{
  if(!path) path='C:\\\\';
  currentPath=path;
  document.getElementById('path-input').value=path;
  document.getElementById('files-output').innerHTML='<p style="color:#3b82f6">⏳ Browsing '+path+'...</p>';
  sendStructured('__ts:ls:'+path,function(err,data){{
    if(err){{ document.getElementById('files-output').innerHTML='<p style="color:#ef4444">❌ '+err+'</p>'; return; }}
    if(data.error){{ document.getElementById('files-output').innerHTML='<p style="color:#ef4444">❌ '+data.error+'</p>'; return; }}
    currentPath=data.path||path;
    document.getElementById('path-input').value=currentPath;
    var files=data.files||[];
    var h='<p style="color:#888;font-size:0.8rem">'+files.length+' items in '+currentPath+'</p>';
    h+='<table><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Action</th></tr></thead><tbody>';
    if(data.parent){{
      h+='<tr><td colspan="4"><a href="#" onclick="browseTo(\\''+data.parent.replace(/\\\\/g,'\\\\\\\\')+'\\')" style="color:#3b82f6">⬆ ..</a></td></tr>';
    }}
    files.forEach(function(f){{
      var icon=f.is_dir?'📁':'📄';
      var nameHtml=f.is_dir?'<a href="#" onclick="browseTo(\\''+((currentPath.endsWith('\\\\')||currentPath.endsWith('/'))?currentPath:currentPath+'\\\\')+f.name.replace(/\\\\/g,'\\\\\\\\')+'\\')" style="color:#3b82f6">'+icon+' '+f.name+'</a>':icon+' '+f.name;
      var dl=f.is_dir?'':'<button onclick="downloadFile(\\''+((currentPath.endsWith('\\\\')||currentPath.endsWith('/'))?currentPath:currentPath+'\\\\')+f.name.replace(/\\\\/g,'\\\\\\\\')+'\\')" class="qcmd">⬇ Download</button>';
      h+='<tr><td>'+nameHtml+'</td><td style="color:#888">'+(!f.is_dir?fmtSize(f.size):'—')+'</td><td style="color:#888">'+(f.modified||'')+'</td><td>'+dl+'</td></tr>';
    }});
    h+='</tbody></table>';
    document.getElementById('files-output').innerHTML=h;
  }});
}}
function downloadFile(path){{
  sendStructured('__ts:download:'+path,function(err,data){{
    if(err){{ alert('Error: '+err); return; }}
    if(data.error){{ alert('Error: '+data.error); return; }}
    // Decode base64 and trigger download
    try{{
      var binary=atob(data.content_base64);
      var bytes=new Uint8Array(binary.length);
      for(var i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
      var blob=new Blob([bytes]);
      var url=URL.createObjectURL(blob);
      var a=document.createElement('a');
      a.href=url; a.download=data.filename||'file'; a.click();
      URL.revokeObjectURL(url);
    }}catch(e){{ alert('Download error: '+e.message); }}
  }});
}}

// ── Messaging ──
function sendMessage(){{
  var input=document.getElementById('msg-input');
  var msgType=document.getElementById('msg-type').value;
  var text=input.value.trim();
  if(!text) return;
  var statusDiv=document.getElementById('msg-status');
  statusDiv.style.display='block'; statusDiv.style.background='rgba(59,130,246,0.15)'; statusDiv.style.color='#3b82f6';
  statusDiv.textContent='📤 Sending...';
  getApiKey().then(function(key){{
    return fetch(apiBase+'/api/v1/monitors/'+monitorId+'/messages',{{
      method:'POST',headers:{{'Content-Type':'application/json','X-TS-API-Key':key}},
      body:JSON.stringify({{message:text,msg_type:msgType}})
    }});
  }}).then(function(r){{return r.json()}}).then(function(data){{
    if(data.id){{
      statusDiv.style.background='rgba(34,197,94,0.15)'; statusDiv.style.color='#22c55e';
      statusDiv.textContent='✅ Message queued — will display on agent next heartbeat';
      input.value='';
      loadMsgHistory();
    }} else {{
      statusDiv.style.background='rgba(239,68,68,0.15)'; statusDiv.style.color='#ef4444';
      statusDiv.textContent='❌ '+(data.detail||'Failed');
    }}
  }}).catch(function(e){{
    statusDiv.style.background='rgba(239,68,68,0.15)'; statusDiv.style.color='#ef4444';
    statusDiv.textContent='❌ '+e.message;
  }});
}}
function loadMsgHistory(){{
  fetch(apiBase+'/api/v1/monitors/'+monitorId+'/messages?limit=20').then(function(r){{return r.json()}}).then(function(msgs){{
    if(!msgs.length){{ document.getElementById('msg-history').innerHTML='<p style="color:#888">No messages yet</p>'; return; }}
    var h='<table><thead><tr><th>Type</th><th>Message</th><th>Sent</th><th>Status</th></tr></thead><tbody>';
    msgs.forEach(function(m){{
      var icons={{"info":"💬","warning":"⚠️","alert":"🚨"}};
      var stColor=m.status==='delivered'?'#22c55e':'#f59e0b';
      var stIcon=m.status==='delivered'?'✅':'⏳';
      h+='<tr><td>'+(icons[m.msg_type]||'💬')+' '+m.msg_type+'</td><td>'+m.message+'</td><td class="ts">'+(m.created_at||'').substring(0,19)+'</td><td style="color:'+stColor+'">'+stIcon+' '+m.status+'</td></tr>';
    }});
    h+='</tbody></table>';
    document.getElementById('msg-history').innerHTML=h;
  }});
}}

// ── WebSocket Real-Time Updates ──
(function(){{
  var wsUrl = 'ws://' + location.hostname + ':8000/ws/status';
  var ws = null;
  var reconnectDelay = 1000;
  var statusEl = document.getElementById('ws-status');

  function setWsStatus(state, text){{
    if(!statusEl) return;
    var dot = statusEl.querySelector('.ws-indicator');
    if(dot) dot.className = 'ws-indicator ws-' + state;
    statusEl.lastChild.textContent = text;
  }}

  function connect(){{
    ws = new WebSocket(wsUrl);
    ws.onopen = function(){{
      reconnectDelay = 1000;
      setWsStatus('connected', 'live updates active');
      ws._pingInterval = setInterval(function(){{ try{{ ws.send('ping'); }}catch(e){{}} }}, 25000);
    }};
    ws.onclose = function(){{
      clearInterval(ws._pingInterval);
      setWsStatus('disconnected', 'reconnecting...');
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
    }};
    ws.onerror = function(){{ ws.close(); }};
    ws.onmessage = function(evt){{
      try{{
        var msg = JSON.parse(evt.data);
        if(msg.type === 'status_update' && msg.monitor_id === monitorId){{
          // Update status dot and text in header
          var headerDot = document.querySelector('.detail-card .status-dot');
          if(headerDot) headerDot.className = 'status-dot dot-' + msg.status;
          var headerBadge = document.querySelector('.detail-card .status-badge');
          if(headerBadge){{
            var dotEl = headerBadge.querySelector('.status-dot');
            headerBadge.innerHTML = '';
            if(dotEl) headerBadge.appendChild(dotEl);
            headerBadge.appendChild(document.createTextNode(' ' + msg.status.toUpperCase()));
          }}

          // Add new row to recent checks table
          var tbody = document.querySelector('.detail-card table');
          if(tbody){{
            var rows = tbody.querySelectorAll('tr');
            if(rows.length > 21) rows[rows.length-1].remove(); // keep ~20 rows
            var newRow = tbody.insertRow(1);
            var sColor = msg.status==='up'?'#22c55e':(msg.status==='down'?'#ef4444':'#f59e0b');
            var t = new Date(msg.checked_at);
            var tStr = t.toLocaleString(undefined, {{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true}});
            newRow.innerHTML = '<td><span class="status-dot dot-'+msg.status+'" style="width:8px;height:8px;display:inline-block;vertical-align:middle;margin-right:4px"></span> '+msg.status+'</td><td>'+(msg.response_time_ms?msg.response_time_ms.toFixed(1)+'ms':'—')+'</td><td>'+tStr+'</td><td style="color:#888;max-width:200px;overflow:hidden;text-overflow:ellipsis">'+(msg.error||'—')+'</td>';
            newRow.style.background = 'rgba(59,130,246,0.08)';
            setTimeout(function(){{ newRow.style.background=''; }}, 2000);
          }}
        }}
      }}catch(e){{}}
    }};
  }}

  connect();
  // Fallback: full page reload every 5 minutes
  setTimeout(function(){{ location.reload(); }}, 300000);
}})();
</script>
</body></html>"""

    # ── RDP File Download Endpoint ───────────────────────────────────
    @app.get("/rdp/{monitor_id}", include_in_schema=False)
    async def rdp_download(monitor_id: str):
        from windows.local_database import get_monitor
        m = get_monitor(monitor_id)
        if not m:
            return HTMLResponse("<h1>Monitor not found</h1>", status_code=404)
        try:
            cfg = m.get("config", "{}")
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            ip = cfg.get("local_ip", "")
            hostname = cfg.get("hostname", "unknown")
        except Exception:
            ip = ""
            hostname = "unknown"
        if not ip or ip == "unknown":
            return HTMLResponse("<h1>No IP address available for this agent</h1>", status_code=400)
        rdp_content = (
            f"full address:s:{ip}\r\n"
            f"prompt for credentials:i:1\r\n"
            f"administrative session:i:1\r\n"
            f"screen mode id:i:2\r\n"
            f"desktopwidth:i:1920\r\n"
            f"desktopheight:i:1080\r\n"
        )
        from fastapi.responses import Response
        return Response(
            content=rdp_content,
            media_type="application/x-rdp",
            headers={"Content-Disposition": f"attachment; filename={hostname}.rdp"}
        )

    @app.get("/vnc/{monitor_id}", include_in_schema=False)
    async def vnc_redirect(monitor_id: str):
        from windows.local_database import get_monitor
        m = get_monitor(monitor_id)
        if not m:
            return HTMLResponse("<h1>Monitor not found</h1>", status_code=404)
        try:
            cfg = m.get("config", "{}")
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            ip = cfg.get("local_ip", "")
        except Exception:
            ip = ""
        if not ip or ip == "unknown":
            return HTMLResponse("<h1>No IP address available for this agent</h1>", status_code=400)
        return RedirectResponse(url=f"vnc://{ip}:5900")

    # ── Incidents Page ───────────────────────────────────────────────────
    @app.get("/incidents", response_class=HTMLResponse)
    async def incidents_page():
        from windows.local_database import get_incidents

        incidents = get_incidents(limit=100)
        rows = ""
        for inc in incidents:
            event_icon = "🚨" if inc["event"] == "down" else "✅"
            duration = ""
            if inc.get("duration_sec"):
                mins = inc["duration_sec"] / 60
                duration = f"{mins:.0f}m" if mins < 60 else f"{mins/60:.1f}h"
            resolved = inc.get("resolved_at", "")[:19] if inc.get("resolved_at") else '<span style="color:#ef4444">Ongoing</span>'
            channels = ", ".join(json.loads(inc.get("channels_notified", "[]"))) if inc.get("channels_notified") else "-"
            rows += f"""<tr>
                <td>{event_icon} {inc['event']}</td>
                <td><strong>{inc.get('monitor_name','?')}</strong></td>
                <td class="ts">{inc.get('started_at','')[:19]}</td>
                <td class="ts">{resolved}</td>
                <td>{duration}</td>
                <td style="color:#888">{channels}</td>
                <td style="color:#888;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{inc.get('error','')[:80]}</td>
            </tr>"""

        if not rows:
            rows = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:#888">No incidents recorded yet</td></tr>'

        branding = _get_branding()
        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3",
                     "accent": branding.get("accent_color", "#3b82f6")}

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Incidents — {branding['app_name']}</title>
<style>{_render_css(defaults)}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #333750; }}
  th {{ color: #8b8fa3; font-size: 0.8rem; text-transform: uppercase; }}
</style>
</head><body>
<div class="container">
  <header><h1>🚨 Incident History</h1>
    <p class="tenant">{len(incidents)} incidents recorded</p>
  </header>
  <div class="toolbar">
    <div><a href="javascript:history.back()" class="btn">← Back</a> <a href="/" class="btn">🏠 Status Pages</a> <a href="/manage" class="btn">🔧 Manage</a></div>
  </div>
  <div style="overflow-x:auto"><table>
    <tr><th>Event</th><th>Monitor</th><th>Started</th><th>Resolved</th><th>Duration</th><th>Channels</th><th>Error</th></tr>
    {rows}
  </table></div>
  <footer>{branding['footer_html']}</footer>
</div>
<script>
document.querySelectorAll('.ts').forEach(function(el){{
  var raw = el.textContent.trim();
  if(!raw || raw==='Ongoing') return;
  try{{
    var d = new Date(raw.replace(' ','T')+'Z');
    if(isNaN(d)) return;
    el.textContent = d.toLocaleString(undefined, {{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true}});
    el.title = raw + ' UTC';
  }}catch(e){{}}
}});
</script>
</body></html>"""

    # ── Audit Log Page ───────────────────────────────────────────────────
    @app.get("/audit", response_class=HTMLResponse)
    async def audit_page():
        from windows.local_database import get_audit_log

        entries = get_audit_log(limit=200)
        rows = ""
        for e in entries:
            action = e.get("action", "")
            action_icons = {"command_sent": "🔧", "wake_on_lan": "⚡", "file_upload": "📤",
                           "file_delete": "🗑️", "message_sent": "💬", "service_action": "⚙️",
                           "process_kill": "💀", "login": "🔑"}
            icon = action_icons.get(action, "📝")
            rows += f"""<tr>
                <td class="ts">{(e.get('timestamp',''))[:19]}</td>
                <td>{icon} {action}</td>
                <td>{e.get('target_type','')}</td>
                <td><strong>{e.get('target_name','')}</strong></td>
                <td style="color:#888;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{e.get('detail','')[:80]}</td>
                <td style="color:#888">{e.get('user','')}</td>
            </tr>"""

        if not rows:
            rows = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:#888">No activity recorded yet</td></tr>'

        branding = _get_branding()
        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3",
                     "accent": branding.get("accent_color", "#3b82f6")}

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Audit Log — {branding['app_name']}</title>
<style>{_render_css(defaults)}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #333750; }}
  th {{ color: #8b8fa3; font-size: 0.8rem; text-transform: uppercase; }}
</style>
</head><body>
<div class="container">
  <header><h1>📝 Activity / Audit Log</h1>
    <p class="tenant">{len(entries)} entries</p>
  </header>
  <div class="toolbar">
    <div><a href="javascript:history.back()" class="btn">← Back</a> <a href="/" class="btn">🏠 Home</a> <a href="/incidents" class="btn">🚨 Incidents</a> <a href="/files" class="btn">☁️ Files</a></div>
  </div>
  <div style="overflow-x:auto"><table>
    <tr><th>Time</th><th>Action</th><th>Type</th><th>Target</th><th>Detail</th><th>User</th></tr>
    {rows}
  </table></div>
  <footer>{branding['footer_html']}</footer>
</div>
<script>
document.querySelectorAll('.ts').forEach(function(el){{
  var raw = el.textContent.trim();
  if(!raw || raw==='Ongoing') return;
  try{{
    var d = new Date(raw.replace(' ','T')+'Z');
    if(isNaN(d)) return;
    el.textContent = d.toLocaleString(undefined, {{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true}});
    el.title = raw + ' UTC';
  }}catch(e){{}}
}});
</script>
</body></html>"""

    # ── File Storage Page ────────────────────────────────────────────────
    @app.get("/files", response_class=HTMLResponse)
    async def files_page():
        from windows.local_database import list_server_files

        files = list_server_files(limit=100)
        rows = ""
        for f in files:
            size = f.get("size", 0)
            if size > 1073741824:
                size_str = f"{size/1073741824:.1f} GB"
            elif size > 1048576:
                size_str = f"{size/1048576:.1f} MB"
            elif size > 1024:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size} B"

            rows += f"""<tr>
                <td>📄 <strong>{f.get('original_name','?')}</strong></td>
                <td>{size_str}</td>
                <td style="color:#888">{f.get('description','')}</td>
                <td>{f.get('download_count',0)}</td>
                <td class="ts">{(f.get('created_at',''))[:19]}</td>
                <td>
                  <a href="/api/v1/files/{f['id']}/download" style="color:#3b82f6;text-decoration:none">⬇ Download</a>
                </td>
            </tr>"""

        if not rows:
            rows = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:#888">No files uploaded yet</td></tr>'

        branding = _get_branding()
        defaults = {"bg_primary": "#0f1117", "bg_secondary": "#1a1d27", "bg_card": "#222636",
                     "text_primary": "#e1e4ed", "text_secondary": "#8b8fa3",
                     "accent": branding.get("accent_color", "#3b82f6")}
        api_base = "http://' + location.hostname + ':8000"

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>File Storage — {branding['app_name']}</title>
<style>{_render_css(defaults)}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #333750; }}
  th {{ color: #8b8fa3; font-size: 0.8rem; text-transform: uppercase; }}
  .upload-area {{ background: var(--bg-card); border: 2px dashed #333750; border-radius: 12px; padding: 2rem; text-align: center; margin-bottom: 1.5rem; cursor: pointer; }}
  .upload-area:hover {{ border-color: #3b82f6; }}
  .upload-area.dragging {{ border-color: #3b82f6; background: rgba(59,130,246,0.05); }}
</style>
</head><body>
<div class="container">
  <header><h1>☁️ Server File Storage</h1>
    <p class="tenant">{len(files)} files stored</p>
  </header>
  <div class="toolbar">
    <div><a href="javascript:history.back()" class="btn">← Back</a> <a href="/" class="btn">🏠 Home</a> <a href="/audit" class="btn">📝 Audit Log</a></div>
  </div>

  <div class="upload-area" id="upload-area" onclick="document.getElementById('file-input').click()"
       ondragover="event.preventDefault();this.classList.add('dragging')"
       ondragleave="this.classList.remove('dragging')"
       ondrop="event.preventDefault();this.classList.remove('dragging');handleDrop(event)">
    <p style="font-size:1.2rem;margin:0">📤 Click or drag files here to upload</p>
    <p style="color:#888;margin:0.5rem 0 0;font-size:0.85rem">Files are stored on the server and available for download by anyone with access</p>
    <input type="file" id="file-input" style="display:none" onchange="uploadFile(this.files[0])">
  </div>
  <div id="upload-status" style="display:none;padding:0.75rem;border-radius:8px;margin-bottom:1rem;font-size:0.85rem"></div>

  <div style="overflow-x:auto"><table>
    <tr><th>File</th><th>Size</th><th>Description</th><th>Downloads</th><th>Uploaded</th><th>Action</th></tr>
    {rows}
  </table></div>
  <footer>{branding['footer_html']}</footer>
</div>
<script>
var apiBase = 'http://' + location.hostname + ':8000';
document.querySelectorAll('.ts').forEach(function(el){{
  var raw = el.textContent.trim();
  if(!raw) return;
  try{{
    var d = new Date(raw.replace(' ','T')+'Z');
    if(isNaN(d)) return;
    el.textContent = d.toLocaleString(undefined, {{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true}});
  }}catch(e){{}}
}});

function handleDrop(e){{ if(e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]); }}

function uploadFile(file){{
  if(!file) return;
  var status = document.getElementById('upload-status');
  status.style.display='block'; status.style.background='rgba(59,130,246,0.15)'; status.style.color='#3b82f6';
  status.textContent='📤 Uploading '+file.name+' ('+Math.round(file.size/1024)+' KB)...';

  var form = new FormData();
  form.append('file', file);
  form.append('description', '');

  fetch(apiBase + '/api/v1/files/upload', {{method:'POST', body: form}})
    .then(function(r){{ return r.json(); }})
    .then(function(data){{
      if(data.id){{
        status.style.background='rgba(34,197,94,0.15)'; status.style.color='#22c55e';
        status.textContent='✅ Uploaded: '+data.original_name;
        setTimeout(function(){{ location.reload(); }}, 1500);
      }} else {{
        status.style.background='rgba(239,68,68,0.15)'; status.style.color='#ef4444';
        status.textContent='❌ '+(data.detail||'Upload failed');
      }}
    }})
    .catch(function(e){{
      status.style.background='rgba(239,68,68,0.15)'; status.style.color='#ef4444';
      status.textContent='❌ '+e.message;
    }});
}}
</script>
</body></html>"""

    return app


def _add_monitor_to_status_pages(tenant_id: str, monitor_id: str):
    """Auto-add new monitor to existing status pages for this tenant."""
    from windows.local_database import _get_conn
    import json as _json

    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, monitor_ids FROM status_pages WHERE tenant_id = ?", (tenant_id,)
    ).fetchall()

    for row in rows:
        ids = _json.loads(row["monitor_ids"]) if isinstance(row["monitor_ids"], str) else row["monitor_ids"]
        if monitor_id not in ids:
            ids.append(monitor_id)
            conn.execute(
                "UPDATE status_pages SET monitor_ids = ? WHERE id = ?",
                (_json.dumps(ids), row["id"]),
            )
    conn.commit()
