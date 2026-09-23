"""
Tech Sentinel Monitor — Local API Server (SQLite-backed)
Standalone FastAPI server for Windows operation without Docker.
Same endpoints as the Docker control-plane, but uses SQLite + in-memory queue.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Security, status, UploadFile, Form, WebSocket, WebSocketDisconnect
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from jose import JWTError, jwt

from windows.local_database import (
    create_tenant, get_tenant, get_tenant_by_slug, get_tenant_by_api_key,
    list_tenants, delete_tenant,
    create_monitor, get_monitor, list_monitors, update_monitor_status, delete_monitor,
    create_alert_channel, list_alert_channels,
    create_status_page, get_status_page_by_slug,
    insert_check_result, get_recent_results, _get_conn,
    insert_performance_record, get_performance_history,
    create_remote_command, get_pending_commands, update_command_result,
    mark_command_started, get_command_history, get_command,
    log_audit, get_audit_log,
    create_server_file, list_server_files, get_server_file, increment_download_count, delete_server_file,
    create_agent_message, get_pending_messages, mark_message_delivered, get_message_history,
)
from windows.local_queue import enqueue_job
from windows.local_version_control import APP_VERSION

logger = logging.getLogger("ts.local_api")

# ── Config ───────────────────────────────────────────────────────────────────

def _load_jwt_secret() -> str:
    """JWT signing secret: TS_JWT_SECRET if set, else a random per-install secret.

    The generated secret is created on first run and kept next to the local database
    (%LOCALAPPDATA%/TechSentinelMonitor/jwt_secret) so tokens survive restarts.
    """
    env_secret = os.environ.get("TS_JWT_SECRET")
    if env_secret:
        return env_secret
    import secrets as _secrets
    secret_dir = os.path.join(os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor")
    secret_path = os.path.join(secret_dir, "jwt_secret")
    try:
        with open(secret_path, "r", encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing
    except OSError:
        pass
    new_secret = _secrets.token_urlsafe(48)
    try:
        os.makedirs(secret_dir, exist_ok=True)
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(new_secret)
    except OSError as e:
        logger.warning(f"Could not persist JWT secret ({e}); logins will reset on restart")
    return new_secret


JWT_SECRET = _load_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

# ── Auth ─────────────────────────────────────────────────────────────────────

api_key_header = APIKeyHeader(name="X-TS-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(tenant_id: str) -> tuple[str, int]:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": tenant_id, "exp": expire}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, JWT_EXPIRE_MINUTES * 60


async def get_current_tenant(
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    if api_key:
        tenant = get_tenant_by_api_key(api_key)
        if tenant:
            return tenant
    if bearer:
        try:
            payload = jwt.decode(bearer.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            tenant_id = payload.get("sub")
            if tenant_id:
                tenant = get_tenant(tenant_id)
                if tenant:
                    return tenant
        except JWTError:
            pass
    raise HTTPException(status_code=401, detail="Invalid API key or token")


# ── Schemas ──────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")

class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    monitor_type: str = Field(..., pattern=r"^(http|tcp|ping|heartbeat)$")
    target: str = Field(..., min_length=1)
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    external_id: str | None = None
    config: dict | None = None
    group_name: str = Field(default="", max_length=100)

class MonitorStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(active|paused)$")

class AlertChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    channel_type: str = Field(..., pattern=r"^(webhook|slack|pagerduty|ts_automation)$")
    config: dict = Field(default_factory=dict)
    external_id: str | None = None

class StatusPageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")
    theme: dict | None = None
    monitor_ids: list[str] | None = None
    external_id: str | None = None

class TokenRequest(BaseModel):
    api_key: str

class HeartbeatPayload(BaseModel):
    system_info: dict | None = None

class RemoteCommandCreate(BaseModel):
    command: str = Field(..., min_length=1, max_length=4096)

class RemoteCommandResult(BaseModel):
    output: str = ""
    exit_code: int = 0
    status: str = "completed"

class AgentMessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    msg_type: str = Field(default="info", pattern=r"^(info|warning|alert)$")


# ── WebSocket Connection Manager ─────────────────────────────────────────────

class WSConnectionManager:
    """Manages WebSocket connections for real-time status broadcasting."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remain)", len(self.active_connections))

    async def broadcast(self, message: dict):
        """Send a JSON message to all connected WebSocket clients."""
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_sync(self, message: dict):
        """Thread-safe broadcast from sync code (probe worker)."""
        import asyncio
        dead = []
        for ws in self.active_connections:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(ws.send_json(message))
                else:
                    loop.run_until_complete(ws.send_json(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = WSConnectionManager()


# ── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Local API server started")
    yield
    logger.info("Local API server stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tech Sentinel Monitor — Local API",
        description="Standalone Windows mode (SQLite + in-memory queue)",
        version=APP_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    # ── Root / Landing ─────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        tenants_list = list_tenants()
        tenant_rows = ""
        for t in tenants_list:
            tenant_rows += f"""<tr>
                <td>{t['name']}</td><td><code>{t['slug']}</code></td>
                <td><code style="font-size:0.8em">{t['api_key']}</code></td>
                <td><code style="font-size:0.8em">{t['id']}</code></td>
            </tr>"""
        if not tenant_rows:
            tenant_rows = '<tr><td colspan="4" style="text-align:center;color:#888">No tenants yet — run the demo or provision via API</td></tr>'

        return f"""<!DOCTYPE html>
<html><head>
<title>Tech Sentinel Monitor — Control Plane</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e1e4ed; margin: 0; padding: 2rem; }}
  h1 {{ color: #3b82f6; }} h2 {{ color: #8b8fa3; margin-top: 2rem; }}
  a {{ color: #3b82f6; text-decoration: none; }} a:hover {{ text-decoration: underline; }}
  .card {{ background: #1a1d27; border-radius: 10px; padding: 1.5rem; margin: 1rem 0; border: 1px solid #333750; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #333750; }}
  th {{ color: #8b8fa3; font-size: 0.85rem; text-transform: uppercase; }}
  code {{ background: #222636; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
  .links {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
  .link-btn {{ background: #222636; padding: 0.7rem 1.2rem; border-radius: 8px; border: 1px solid #333750; }}
  .link-btn:hover {{ border-color: #3b82f6; }}
  .badge {{ background: #22c55e22; color: #22c55e; padding: 4px 12px; border-radius: 12px; font-size: 0.85rem; }}
</style>
</head><body>
<h1>🛡️ Tech Sentinel Monitor</h1>
<p>Control Plane API — <span class="badge">● Running</span> &nbsp; Windows Standalone Mode</p>

<div class="card">
  <h2 style="margin-top:0">🔗 Quick Links</h2>
  <div class="links">
    <a class="link-btn" href="/docs">📖 API Docs (Swagger)</a>
    <a class="link-btn" href="/redoc">📄 ReDoc</a>
    <a class="link-btn" href="/health">💚 Health Check</a>
    <a class="link-btn" href="//" id="sp-link">📊 Status Pages</a>
    <script>document.getElementById('sp-link').href='http://'+location.hostname+':8001';</script>
  </div>
</div>

<div class="card">
  <h2 style="margin-top:0">🏢 Tenants</h2>
  <table>
    <tr><th>Name</th><th>Slug</th><th>API Key</th><th>ID</th></tr>
    {tenant_rows}
  </table>
</div>

<div class="card">
  <h2 style="margin-top:0">📡 API Endpoints</h2>
  <table>
    <tr><th>Method</th><th>Endpoint</th><th>Description</th></tr>
    <tr><td><code>POST</code></td><td><a href="/docs#/tenants">/api/v1/tenants/</a></td><td>Create tenant</td></tr>
    <tr><td><code>GET</code></td><td><a href="/api/v1/tenants/">/api/v1/tenants/</a></td><td>List tenants</td></tr>
    <tr><td><code>POST</code></td><td><a href="/docs#/monitors">/api/v1/monitors/</a></td><td>Create monitor (auth required)</td></tr>
    <tr><td><code>POST</code></td><td><a href="/docs#/alerts">/api/v1/alert-channels/</a></td><td>Create alert channel</td></tr>
    <tr><td><code>POST</code></td><td><a href="/docs#/status-pages">/api/v1/status-pages/</a></td><td>Create status page</td></tr>
    <tr><td><code>POST</code></td><td><a href="/docs#/heartbeat">/api/v1/heartbeat/{{id}}</a></td><td>Record heartbeat</td></tr>
    <tr><td><code>POST</code></td><td><a href="/docs#/auth">/api/v1/auth/token</a></td><td>Get JWT token</td></tr>
  </table>
</div>

<p style="color:#555;margin-top:2rem;font-size:0.85rem">Tech Sentinel Monitor v{APP_VERSION} — REGTeches / Ronald Goodchild</p>
</body></html>"""

    # ── Health ───────────────────────────────────────────────────────────
    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "service": "control-plane-local", "mode": "windows-standalone"}

    # ── Tenants ──────────────────────────────────────────────────────────
    @app.post("/api/v1/tenants/", status_code=201, tags=["tenants"])
    async def create_tenant_ep(body: TenantCreate):
        return create_tenant(name=body.name, slug=body.slug)

    @app.get("/api/v1/tenants/", tags=["tenants"])
    async def list_tenants_ep():
        return list_tenants()

    @app.get("/api/v1/tenants/{tenant_id}", tags=["tenants"])
    async def get_tenant_ep(tenant_id: str):
        t = get_tenant(tenant_id)
        if not t:
            raise HTTPException(404, "Tenant not found")
        return t

    @app.delete("/api/v1/tenants/{tenant_id}", status_code=204, tags=["tenants"])
    async def delete_tenant_ep(tenant_id: str):
        t = get_tenant(tenant_id)
        if not t:
            raise HTTPException(404, "Tenant not found")
        delete_tenant(tenant_id)

    # ── Monitors ─────────────────────────────────────────────────────────
    @app.post("/api/v1/monitors/", status_code=201, tags=["monitors"])
    async def create_monitor_ep(body: MonitorCreate, tenant=Depends(get_current_tenant)):
        monitor = create_monitor(
            tenant_id=tenant["id"], name=body.name,
            monitor_type=body.monitor_type, target=body.target,
            interval_seconds=body.interval_seconds,
            timeout_seconds=body.timeout_seconds,
            external_id=body.external_id, config=body.config,
            group_name=body.group_name,
        )
        # Enqueue for local probe worker
        enqueue_job({
            "monitor_id": monitor["id"],
            "tenant_id": monitor["tenant_id"],
            "monitor_type": monitor["monitor_type"],
            "target": monitor["target"],
            "interval_seconds": str(monitor["interval_seconds"]),
            "timeout_seconds": str(monitor["timeout_seconds"]),
            "config": monitor.get("config", "{}"),
        })

        # Auto-add to all status pages for this tenant
        try:
            import json as _json
            conn = _get_conn()
            pages = conn.execute(
                "SELECT id, monitor_ids FROM status_pages WHERE tenant_id = ?",
                (tenant["id"],),
            ).fetchall()
            for page in pages:
                ids = _json.loads(page["monitor_ids"]) if isinstance(page["monitor_ids"], str) else page["monitor_ids"]
                if monitor["id"] not in ids:
                    ids.append(monitor["id"])
                    conn.execute(
                        "UPDATE status_pages SET monitor_ids = ? WHERE id = ?",
                        (_json.dumps(ids), page["id"]),
                    )
            conn.commit()
        except Exception:
            pass  # Non-critical

        return monitor

    @app.get("/api/v1/monitors/", tags=["monitors"])
    async def list_monitors_ep(tenant=Depends(get_current_tenant)):
        return list_monitors(tenant["id"])

    @app.get("/api/v1/monitors/{monitor_id}", tags=["monitors"])
    async def get_monitor_ep(monitor_id: str, tenant=Depends(get_current_tenant)):
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")
        return m

    @app.patch("/api/v1/monitors/{monitor_id}/status", tags=["monitors"])
    async def update_status_ep(monitor_id: str, body: MonitorStatusUpdate, tenant=Depends(get_current_tenant)):
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")
        update_monitor_status(monitor_id, body.status)
        m["status"] = body.status
        return m

    @app.delete("/api/v1/monitors/{monitor_id}", status_code=204, tags=["monitors"])
    async def delete_monitor_ep(monitor_id: str, tenant=Depends(get_current_tenant)):
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")
        delete_monitor(monitor_id)

    @app.get("/api/v1/monitors/{monitor_id}/results", tags=["monitors"])
    async def get_results_ep(monitor_id: str, limit: int = 10, tenant=Depends(get_current_tenant)):
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")
        return get_recent_results(monitor_id, limit=min(limit, 100))

    # ── Alert Channels ───────────────────────────────────────────────────
    @app.post("/api/v1/alert-channels/", status_code=201, tags=["alerts"])
    async def create_channel_ep(body: AlertChannelCreate, tenant=Depends(get_current_tenant)):
        return create_alert_channel(
            tenant_id=tenant["id"], name=body.name,
            channel_type=body.channel_type, config=body.config,
            external_id=body.external_id,
        )

    @app.get("/api/v1/alert-channels/", tags=["alerts"])
    async def list_channels_ep(tenant=Depends(get_current_tenant)):
        return list_alert_channels(tenant["id"])

    # ── Status Pages ─────────────────────────────────────────────────────
    @app.post("/api/v1/status-pages/", status_code=201, tags=["status-pages"])
    async def create_page_ep(body: StatusPageCreate, tenant=Depends(get_current_tenant)):
        return create_status_page(
            tenant_id=tenant["id"], name=body.name, slug=body.slug,
            theme=body.theme, monitor_ids=body.monitor_ids,
            external_id=body.external_id,
        )

    @app.get("/api/v1/status-pages/{slug}", tags=["status-pages"])
    async def get_page_ep(slug: str):
        p = get_status_page_by_slug(slug)
        if not p:
            raise HTTPException(404, "Status page not found")
        return p

    # ── Heartbeat ────────────────────────────────────────────────────────
    @app.post("/api/v1/heartbeat/{monitor_id}", tags=["heartbeat"])
    async def heartbeat_ep(monitor_id: str, body: HeartbeatPayload = HeartbeatPayload()):
        m = get_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")
        if m["monitor_type"] != "heartbeat":
            raise HTTPException(400, "Not a heartbeat monitor")
        insert_check_result(monitor_id=monitor_id, status="up", response_time_ms=0)

        # Broadcast "up" via WebSocket so status page updates in real-time
        try:
            await broadcast_status_update(monitor_id, {"status": "up", "response_time_ms": 0})
        except Exception:
            pass

        # If system info is provided, store it in the monitor's config
        if body.system_info:
            try:
                import json as _json
                conn = _get_conn()
                conn.execute(
                    "UPDATE monitors SET config=?, updated_at=? WHERE id=?",
                    (_json.dumps(body.system_info), datetime.now(timezone.utc).isoformat(), monitor_id),
                )
                conn.commit()
            except Exception:
                pass  # Non-critical

            # Extract & store performance metrics for trending
            try:
                si = body.system_info
                cpu_pct = None
                ram_pct = None
                disk_pct = None
                disk_detail = []

                if isinstance(si.get("cpu"), dict):
                    cpu_pct = si["cpu"].get("usage_percent")
                if isinstance(si.get("ram"), dict):
                    ram_pct = si["ram"].get("percent_used")
                if isinstance(si.get("disks"), list):
                    disk_detail = si["disks"]
                    # Overall disk % = max usage across all drives
                    pcts = [d.get("percent_used", 0) for d in disk_detail
                            if isinstance(d, dict) and "percent_used" in d]
                    disk_pct = max(pcts) if pcts else None

                insert_performance_record(
                    monitor_id=monitor_id,
                    cpu_percent=cpu_pct,
                    ram_percent=ram_pct,
                    disk_percent=disk_pct,
                    disk_detail=disk_detail,
                )
            except Exception:
                pass  # Non-critical

        # Return pending messages for the agent to display
        from windows.local_database import get_pending_messages as _get_msgs
        pending_msgs = _get_msgs(monitor_id)

        return {"status": "ok", "monitor_id": monitor_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "messages": pending_msgs}

    # ── Performance History ─────────────────────────────────────────────
    @app.get("/api/v1/monitors/{monitor_id}/performance", tags=["monitors"])
    async def get_perf_ep(monitor_id: str, limit: int = 60):
        m = get_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")
        return get_performance_history(monitor_id, limit=min(limit, 500))

    # ── Remote Commands ──────────────────────────────────────────────────
    @app.post("/api/v1/monitors/{monitor_id}/commands", status_code=201, tags=["remote-commands"])
    async def send_command_ep(monitor_id: str, body: RemoteCommandCreate,
                              tenant=Depends(get_current_tenant)):
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")
        if m["monitor_type"] != "heartbeat":
            raise HTTPException(400, "Remote commands only work with agent (heartbeat) monitors")
        log_audit("command_sent", "agent", m["name"], monitor_id=monitor_id,
                  detail=body.command[:200])
        return create_remote_command(monitor_id, body.command)

    @app.get("/api/v1/monitors/{monitor_id}/commands", tags=["remote-commands"])
    async def list_commands_ep(monitor_id: str, limit: int = 50):
        m = get_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")
        return get_command_history(monitor_id, limit=min(limit, 200))

    @app.get("/api/v1/monitors/{monitor_id}/commands/pending", tags=["remote-commands"])
    async def pending_commands_ep(monitor_id: str):
        """Agent polls this endpoint to get pending commands."""
        m = get_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")
        return get_pending_commands(monitor_id)

    @app.post("/api/v1/commands/{cmd_id}/start", tags=["remote-commands"])
    async def start_command_ep(cmd_id: str):
        """Agent marks a command as started."""
        cmd = get_command(cmd_id)
        if not cmd:
            raise HTTPException(404, "Command not found")
        mark_command_started(cmd_id)
        return {"status": "ok"}

    @app.post("/api/v1/commands/{cmd_id}/result", tags=["remote-commands"])
    async def command_result_ep(cmd_id: str, body: RemoteCommandResult):
        """Agent reports command execution result."""
        cmd = get_command(cmd_id)
        if not cmd:
            raise HTTPException(404, "Command not found")
        update_command_result(cmd_id, output=body.output,
                             exit_code=body.exit_code, status=body.status)
        return {"status": "ok"}

    # ── Wake-on-LAN ────────────────────────────────────────────────────
    @app.post("/api/v1/monitors/{monitor_id}/wol", tags=["remote-commands"])
    async def wake_on_lan_ep(monitor_id: str, tenant=Depends(get_current_tenant)):
        """Send Wake-on-LAN magic packet to the agent's machine."""
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")

        # Get MAC address from stored system info
        mac = None
        try:
            cfg = m.get("config", "{}")
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            for iface in cfg.get("network_interfaces", []):
                for addr in iface.get("addresses", []):
                    if addr.get("type") == "IPv4" and not addr.get("address", "").startswith("127."):
                        # Found the interface, look for MAC in psutil format
                        # psutil stores MAC as separate entries with family=17 (AF_LINK)
                        pass
                # Check for MAC address in the interface
                for addr in iface.get("addresses", []):
                    a = addr.get("address", "")
                    # MAC format: XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX
                    if len(a) == 17 and (a.count(":") == 5 or a.count("-") == 5):
                        mac = a.replace("-", ":").upper()
                        break
                if mac:
                    break
        except Exception:
            pass

        if not mac:
            raise HTTPException(400, "No MAC address found for this agent. "
                                     "Ensure the agent has psutil installed for network info.")

        # Send magic packet
        try:
            import socket as _socket
            import struct
            mac_bytes = bytes.fromhex(mac.replace(":", ""))
            magic = b'\xff' * 6 + mac_bytes * 16
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
            sock.sendto(magic, ('<broadcast>', 9))
            sock.close()
            log_audit("wake_on_lan", "agent", m.get("name", monitor_id),
                      monitor_id=monitor_id, detail=f"MAC: {mac}")
            return {"status": "ok", "message": f"Wake-on-LAN sent to {mac}",
                    "mac": mac, "monitor_id": monitor_id}
        except Exception as e:
            raise HTTPException(500, f"Failed to send WoL: {e}")

    # ── Audit Log ────────────────────────────────────────────────────────
    @app.get("/api/v1/audit-log", tags=["audit"])
    async def audit_log_ep(limit: int = 100, monitor_id: str = ""):
        return get_audit_log(limit=min(limit, 500), monitor_id=monitor_id)

    # ── Server File Storage ──────────────────────────────────────────────
    @app.get("/api/v1/files", tags=["files"])
    async def list_files_ep():
        return list_server_files()

    @app.post("/api/v1/files/upload", status_code=201, tags=["files"])
    async def upload_file_ep(file: UploadFile, description: str = Form("")):
        """Upload a file to the server file storage."""
        import os
        storage_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor", "file_storage"
        )
        os.makedirs(storage_dir, exist_ok=True)

        # Generate unique filename
        from uuid import uuid4
        ext = os.path.splitext(file.filename or "file")[1]
        stored_name = f"{uuid4().hex}{ext}"
        file_path = os.path.join(storage_dir, stored_name)

        # Save file
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        record = create_server_file(
            filename=stored_name,
            original_name=file.filename or "unknown",
            size=len(content),
            mime_type=file.content_type or "application/octet-stream",
            description=description,
        )
        log_audit("file_upload", "file", file.filename or "unknown",
                  detail=f"Size: {len(content)} bytes")
        return record

    @app.get("/api/v1/files/{file_id}/download", tags=["files"])
    async def download_file_ep(file_id: str):
        """Download a file from server storage."""
        import os
        from fastapi.responses import FileResponse
        record = get_server_file(file_id)
        if not record:
            raise HTTPException(404, "File not found")
        storage_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor", "file_storage"
        )
        file_path = os.path.join(storage_dir, record["filename"])
        if not os.path.exists(file_path):
            raise HTTPException(404, "File not found on disk")
        increment_download_count(file_id)
        return FileResponse(
            path=file_path,
            filename=record["original_name"],
            media_type=record.get("mime_type", "application/octet-stream"),
        )

    @app.delete("/api/v1/files/{file_id}", status_code=204, tags=["files"])
    async def delete_file_ep(file_id: str, tenant=Depends(get_current_tenant)):
        import os
        record = get_server_file(file_id)
        if not record:
            raise HTTPException(404, "File not found")
        storage_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor", "file_storage"
        )
        file_path = os.path.join(storage_dir, record["filename"])
        try:
            os.remove(file_path)
        except OSError:
            pass
        delete_server_file(file_id)
        log_audit("file_delete", "file", record["original_name"])

    # ── Agent Messages ───────────────────────────────────────────────────
    @app.post("/api/v1/monitors/{monitor_id}/messages", status_code=201, tags=["messages"])
    async def send_message_ep(monitor_id: str, body: AgentMessageCreate,
                              tenant=Depends(get_current_tenant)):
        m = get_monitor(monitor_id)
        if not m or m["tenant_id"] != tenant["id"]:
            raise HTTPException(404, "Monitor not found")
        msg = create_agent_message(monitor_id, body.message, body.msg_type)
        log_audit("message_sent", "agent", m["name"], monitor_id=monitor_id,
                  detail=f"{body.msg_type}: {body.message[:100]}")
        return msg

    @app.get("/api/v1/monitors/{monitor_id}/messages/pending", tags=["messages"])
    async def pending_messages_ep(monitor_id: str):
        return get_pending_messages(monitor_id)

    @app.post("/api/v1/messages/{msg_id}/delivered", tags=["messages"])
    async def message_delivered_ep(msg_id: str):
        mark_message_delivered(msg_id)
        return {"status": "ok"}

    @app.get("/api/v1/monitors/{monitor_id}/messages", tags=["messages"])
    async def message_history_ep(monitor_id: str, limit: int = 50):
        return get_message_history(monitor_id, limit=min(limit, 200))

    # ── Auth Token ───────────────────────────────────────────────────────
    @app.post("/api/v1/auth/token", tags=["auth"])
    async def get_token_ep(body: TokenRequest):
        tenant = get_tenant_by_api_key(body.api_key)
        if not tenant:
            raise HTTPException(401, "Invalid API key")
        token, expires_in = create_access_token(tenant["id"])
        return {"access_token": token, "token_type": "bearer", "expires_in": expires_in}

    # ── WebSocket — Real-Time Status Feed ────────────────────────────────
    @app.websocket("/ws/status")
    async def ws_status_feed(websocket: WebSocket):
        """WebSocket endpoint for real-time monitor status updates.

        Clients connect and receive JSON messages whenever a monitor's
        status changes, eliminating the need for page refreshes.
        Message format:
        {
            "type": "status_update",
            "monitor_id": "...",
            "name": "...",
            "status": "up|down|timeout",
            "response_time_ms": 12.5,
            "error": null,
            "checked_at": "2026-04-13T...",
            "monitor_type": "http|tcp|ping|heartbeat"
        }
        """
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep the connection alive; client can send pings
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception:
            ws_manager.disconnect(websocket)

    return app


async def broadcast_status_update(monitor_id: str, result: dict):
    """Called by probe worker to broadcast a status change via WebSocket."""
    try:
        m = get_monitor(monitor_id)
        msg = {
            "type": "status_update",
            "monitor_id": monitor_id,
            "name": m["name"] if m else monitor_id,
            "monitor_type": m["monitor_type"] if m else "",
            "status": result.get("status", "unknown"),
            "response_time_ms": round(result.get("response_time_ms", 0), 1),
            "status_code": result.get("status_code"),
            "error": result.get("error"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        await ws_manager.broadcast(msg)
    except Exception as e:
        logger.debug("WebSocket broadcast error: %s", e)
