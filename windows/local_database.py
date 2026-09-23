"""
Tech Sentinel Monitor — Local SQLite Database Adapter
Replaces asyncpg/TimescaleDB for standalone Windows operation.
All the same model functions, backed by SQLite instead of PostgreSQL.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from uuid import uuid4

# Thread-local storage for connections
_local = threading.local()
_db_path: str = ""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uuid():
    return str(uuid4())


def init_db(db_path: str = ""):
    """Initialize the SQLite database with the schema."""
    global _db_path
    if not db_path:
        app_data = os.path.join(os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor")
        os.makedirs(app_data, exist_ok=True)
        db_path = os.path.join(app_data, "techsentinel.db")
    _db_path = db_path

    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            slug        TEXT NOT NULL UNIQUE,
            api_key     TEXT NOT NULL UNIQUE,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monitors (
            id               TEXT PRIMARY KEY,
            tenant_id        TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            monitor_type     TEXT NOT NULL,
            target           TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL DEFAULT 60,
            timeout_seconds  INTEGER NOT NULL DEFAULT 10,
            external_id      TEXT,
            config           TEXT NOT NULL DEFAULT '{}',
            status           TEXT NOT NULL DEFAULT 'active',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            UNIQUE (tenant_id, external_id)
        );

        CREATE INDEX IF NOT EXISTS idx_monitors_tenant ON monitors(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_monitors_status ON monitors(status);

        CREATE TABLE IF NOT EXISTS alert_channels (
            id           TEXT PRIMARY KEY,
            tenant_id    TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name         TEXT NOT NULL,
            channel_type TEXT NOT NULL,
            config       TEXT NOT NULL DEFAULT '{}',
            external_id  TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            UNIQUE (tenant_id, external_id)
        );

        CREATE TABLE IF NOT EXISTS status_pages (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            slug        TEXT NOT NULL UNIQUE,
            theme       TEXT NOT NULL DEFAULT '{}',
            monitor_ids TEXT NOT NULL DEFAULT '[]',
            external_id TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            UNIQUE (tenant_id, external_id)
        );

        CREATE TABLE IF NOT EXISTS check_results (
            id               TEXT NOT NULL,
            monitor_id       TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            checked_at       TEXT NOT NULL,
            status           TEXT NOT NULL,
            response_time_ms REAL,
            status_code      INTEGER,
            error            TEXT,
            PRIMARY KEY (id)
        );

        CREATE INDEX IF NOT EXISTS idx_results_monitor ON check_results(monitor_id, checked_at DESC);

        -- v1.1: Incident history log
        CREATE TABLE IF NOT EXISTS incidents (
            id           TEXT PRIMARY KEY,
            monitor_id   TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            monitor_name TEXT NOT NULL,
            event        TEXT NOT NULL,
            started_at   TEXT NOT NULL,
            resolved_at  TEXT,
            duration_sec REAL,
            failures     INTEGER NOT NULL DEFAULT 0,
            error        TEXT,
            channels_notified TEXT NOT NULL DEFAULT '[]',
            created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_monitor ON incidents(monitor_id, created_at DESC);

        -- v1.1: Maintenance windows
        CREATE TABLE IF NOT EXISTS maintenance_windows (
            id          TEXT PRIMARY KEY,
            monitor_id  TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            reason      TEXT NOT NULL DEFAULT 'Scheduled Maintenance',
            start_time  TEXT NOT NULL,
            end_time    TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_maintenance_monitor ON maintenance_windows(monitor_id);

        -- v1.2: Performance history (time-series CPU/RAM/disk)
        CREATE TABLE IF NOT EXISTS performance_history (
            id          TEXT PRIMARY KEY,
            monitor_id  TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            recorded_at TEXT NOT NULL,
            cpu_percent REAL,
            ram_percent REAL,
            disk_percent REAL,
            disk_detail TEXT NOT NULL DEFAULT '[]',
            extra       TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_perf_monitor ON performance_history(monitor_id, recorded_at DESC);

        -- v1.2: Remote commands queue
        CREATE TABLE IF NOT EXISTS remote_commands (
            id           TEXT PRIMARY KEY,
            monitor_id   TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            command      TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            output       TEXT,
            exit_code    INTEGER,
            created_at   TEXT NOT NULL,
            started_at   TEXT,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cmds_monitor ON remote_commands(monitor_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cmds_pending ON remote_commands(status, monitor_id);

        -- v1.3: Audit / Activity Log
        CREATE TABLE IF NOT EXISTS audit_log (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            user        TEXT NOT NULL DEFAULT 'admin',
            action      TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT '',
            target_name TEXT NOT NULL DEFAULT '',
            monitor_id  TEXT,
            detail      TEXT NOT NULL DEFAULT '',
            ip_address  TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_monitor ON audit_log(monitor_id);

        -- v1.3: Server file storage metadata
        CREATE TABLE IF NOT EXISTS server_files (
            id          TEXT PRIMARY KEY,
            filename    TEXT NOT NULL,
            original_name TEXT NOT NULL,
            size        INTEGER NOT NULL DEFAULT 0,
            mime_type   TEXT NOT NULL DEFAULT 'application/octet-stream',
            uploaded_by TEXT NOT NULL DEFAULT 'admin',
            description TEXT NOT NULL DEFAULT '',
            download_count INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_files_time ON server_files(created_at DESC);

        -- v1.3: Agent messages
        CREATE TABLE IF NOT EXISTS agent_messages (
            id          TEXT PRIMARY KEY,
            monitor_id  TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            message     TEXT NOT NULL,
            msg_type    TEXT NOT NULL DEFAULT 'info',
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            delivered_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_msgs_monitor ON agent_messages(monitor_id, status);
    """)

    # v1.1: Add group_name and ssl_expiry columns to monitors (safe if already exists)
    try:
        conn.execute("ALTER TABLE monitors ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE monitors ADD COLUMN ssl_expiry TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    return db_path


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(_db_path, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Tenants ──────────────────────────────────────────────────────────────────

def create_tenant(name: str, slug: str, api_key: str | None = None) -> dict:
    conn = _get_conn()
    tenant_id = _uuid()
    api_key = api_key or _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO tenants (id, name, slug, api_key, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (slug) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at""",
        (tenant_id, name, slug, api_key, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tenants WHERE slug = ?", (slug,)).fetchone()
    return _row_to_dict(row)


def get_tenant(tenant_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    return _row_to_dict(row)


def get_tenant_by_slug(slug: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tenants WHERE slug = ?", (slug,)).fetchone()
    return _row_to_dict(row)


def get_tenant_by_api_key(api_key: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tenants WHERE api_key = ?", (api_key,)).fetchone()
    return _row_to_dict(row)


def list_tenants() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM tenants ORDER BY created_at DESC").fetchall()
    return _rows_to_list(rows)


def delete_tenant(tenant_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
    conn.commit()


# ── Monitors ─────────────────────────────────────────────────────────────────

def create_monitor(
    tenant_id: str, name: str, monitor_type: str, target: str,
    interval_seconds: int = 60, timeout_seconds: int = 10,
    external_id: str | None = None, config: dict | None = None,
    group_name: str = "",
) -> dict:
    conn = _get_conn()
    monitor_id = _uuid()
    now = _now()
    config_json = json.dumps(config or {})
    conn.execute(
        """INSERT INTO monitors
           (id, tenant_id, name, monitor_type, target, interval_seconds,
            timeout_seconds, external_id, config, status, group_name, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,'active',?,?,?)
           ON CONFLICT (tenant_id, external_id)
           DO UPDATE SET name=excluded.name, monitor_type=excluded.monitor_type,
              target=excluded.target, interval_seconds=excluded.interval_seconds,
              timeout_seconds=excluded.timeout_seconds, config=excluded.config,
              group_name=excluded.group_name,
              updated_at=excluded.updated_at""",
        (monitor_id, tenant_id, name, monitor_type, target,
         interval_seconds, timeout_seconds, external_id, config_json, group_name, now, now),
    )
    conn.commit()
    if external_id:
        row = conn.execute(
            "SELECT * FROM monitors WHERE tenant_id=? AND external_id=?",
            (tenant_id, external_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone()
    return _row_to_dict(row)


def get_monitor(monitor_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,)).fetchone()
    return _row_to_dict(row)


def list_monitors(tenant_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM monitors WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)
    ).fetchall()
    return _rows_to_list(rows)


def list_all_active_monitors() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM monitors WHERE status = 'active'").fetchall()
    return _rows_to_list(rows)


def update_monitor_status(monitor_id: str, status: str):
    conn = _get_conn()
    conn.execute(
        "UPDATE monitors SET status=?, updated_at=? WHERE id=?",
        (status, _now(), monitor_id),
    )
    conn.commit()


def delete_monitor(monitor_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
    conn.commit()


# ── Alert Channels ───────────────────────────────────────────────────────────

def create_alert_channel(
    tenant_id: str, name: str, channel_type: str, config: dict,
    external_id: str | None = None,
) -> dict:
    conn = _get_conn()
    channel_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO alert_channels
           (id, tenant_id, name, channel_type, config, external_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT (tenant_id, external_id)
           DO UPDATE SET name=excluded.name, channel_type=excluded.channel_type,
              config=excluded.config, updated_at=excluded.updated_at""",
        (channel_id, tenant_id, name, channel_type, json.dumps(config), external_id, now, now),
    )
    conn.commit()
    if external_id:
        row = conn.execute(
            "SELECT * FROM alert_channels WHERE tenant_id=? AND external_id=?",
            (tenant_id, external_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM alert_channels WHERE id=?", (channel_id,)).fetchone()
    return _row_to_dict(row)


def list_alert_channels(tenant_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM alert_channels WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)
    ).fetchall()
    return _rows_to_list(rows)


# ── Status Pages ─────────────────────────────────────────────────────────────

def create_status_page(
    tenant_id: str, name: str, slug: str,
    theme: dict | None = None, monitor_ids: list | None = None,
    external_id: str | None = None,
) -> dict:
    conn = _get_conn()
    page_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO status_pages
           (id, tenant_id, name, slug, theme, monitor_ids, external_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (tenant_id, external_id)
           DO UPDATE SET name=excluded.name, slug=excluded.slug,
              theme=excluded.theme, monitor_ids=excluded.monitor_ids,
              updated_at=excluded.updated_at""",
        (page_id, tenant_id, name, slug,
         json.dumps(theme or {}), json.dumps(monitor_ids or []),
         external_id, now, now),
    )
    conn.commit()
    if external_id:
        row = conn.execute(
            "SELECT * FROM status_pages WHERE tenant_id=? AND external_id=?",
            (tenant_id, external_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM status_pages WHERE id=?", (page_id,)).fetchone()
    return _row_to_dict(row)


def get_status_page_by_slug(slug: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM status_pages WHERE slug = ?", (slug,)).fetchone()
    return _row_to_dict(row)


# ── Check Results ────────────────────────────────────────────────────────────

def insert_check_result(
    monitor_id: str, status: str,
    response_time_ms: float | None = None,
    status_code: int | None = None,
    error: str | None = None,
):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO check_results (id, monitor_id, checked_at, status, response_time_ms, status_code, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (_uuid(), monitor_id, _now(), status, response_time_ms, status_code, error),
    )
    conn.commit()


def get_recent_results(monitor_id: str, limit: int = 10) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM check_results WHERE monitor_id=? ORDER BY checked_at DESC LIMIT ?",
        (monitor_id, limit),
    ).fetchall()
    return _rows_to_list(rows)


def get_consecutive_failures(monitor_id: str) -> int:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT status FROM check_results WHERE monitor_id=? ORDER BY checked_at DESC LIMIT 100",
        (monitor_id,),
    ).fetchall()
    count = 0
    for r in rows:
        if r["status"] != "up":
            count += 1
        else:
            break
    return count


def cleanup_old_results(days: int = 90):
    """Remove check results older than N days (equivalent to TimescaleDB retention)."""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM check_results WHERE checked_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()


def get_db_path() -> str:
    return _db_path


def get_db_size_mb() -> float:
    if os.path.exists(_db_path):
        return os.path.getsize(_db_path) / (1024 * 1024)
    return 0.0


# ── Uptime Percentages ──────────────────────────────────────────────────────

def get_uptime_percent(monitor_id: str, hours: int = 24) -> float:
    """Calculate uptime percentage over the last N hours."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) as up_count
           FROM check_results
           WHERE monitor_id = ? AND checked_at > datetime('now', ?)""",
        (monitor_id, f"-{hours} hours"),
    ).fetchone()
    total = row["total"] if row else 0
    if total == 0:
        return 0.0
    return (row["up_count"] / total) * 100.0


def get_uptime_stats(monitor_id: str) -> dict:
    """Get 24h, 7d, 30d uptime percentages."""
    return {
        "uptime_24h": round(get_uptime_percent(monitor_id, 24), 2),
        "uptime_7d": round(get_uptime_percent(monitor_id, 168), 2),
        "uptime_30d": round(get_uptime_percent(monitor_id, 720), 2),
    }


def get_response_time_series(monitor_id: str, limit: int = 30) -> list[dict]:
    """Get recent response times for sparkline charts."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT checked_at, response_time_ms, status
           FROM check_results
           WHERE monitor_id = ? AND response_time_ms IS NOT NULL
           ORDER BY checked_at DESC LIMIT ?""",
        (monitor_id, limit),
    ).fetchall()
    return list(reversed(_rows_to_list(rows)))


def get_avg_response_time(monitor_id: str, hours: int = 24) -> float | None:
    """Get average response time over the last N hours."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT AVG(response_time_ms) as avg_ms
           FROM check_results
           WHERE monitor_id = ? AND status = 'up'
             AND checked_at > datetime('now', ?)""",
        (monitor_id, f"-{hours} hours"),
    ).fetchone()
    return round(row["avg_ms"], 1) if row and row["avg_ms"] else None


# ── Incidents ────────────────────────────────────────────────────────────────

def create_incident(
    monitor_id: str, monitor_name: str, event: str,
    failures: int = 0, error: str = "",
    channels_notified: list | None = None,
) -> dict:
    conn = _get_conn()
    inc_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO incidents
           (id, monitor_id, monitor_name, event, started_at, failures,
            error, channels_notified, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (inc_id, monitor_id, monitor_name, event, now, failures,
         error, json.dumps(channels_notified or []), now),
    )
    conn.commit()
    return {"id": inc_id, "monitor_id": monitor_id, "event": event, "started_at": now}


def resolve_incident(monitor_id: str):
    """Resolve the most recent open incident for a monitor."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT id, started_at FROM incidents
           WHERE monitor_id = ? AND resolved_at IS NULL
           ORDER BY created_at DESC LIMIT 1""",
        (monitor_id,),
    ).fetchone()
    if row:
        now = _now()
        started = row["started_at"]
        # Calculate duration in seconds
        try:
            from datetime import datetime as dt
            start_dt = dt.fromisoformat(started)
            end_dt = dt.fromisoformat(now)
            duration = (end_dt - start_dt).total_seconds()
        except Exception:
            duration = 0
        conn.execute(
            "UPDATE incidents SET resolved_at=?, duration_sec=? WHERE id=?",
            (now, duration, row["id"]),
        )
        conn.commit()


def get_incidents(monitor_id: str | None = None, limit: int = 50) -> list[dict]:
    conn = _get_conn()
    if monitor_id:
        rows = conn.execute(
            "SELECT * FROM incidents WHERE monitor_id=? ORDER BY created_at DESC LIMIT ?",
            (monitor_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return _rows_to_list(rows)


# ── Maintenance Windows ──────────────────────────────────────────────────────

def create_maintenance_window(
    monitor_id: str, start_time: str, end_time: str, reason: str = "Scheduled Maintenance",
) -> dict:
    conn = _get_conn()
    mw_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO maintenance_windows (id, monitor_id, reason, start_time, end_time, created_at)
           VALUES (?,?,?,?,?,?)""",
        (mw_id, monitor_id, reason, start_time, end_time, now),
    )
    conn.commit()
    return {"id": mw_id, "monitor_id": monitor_id, "start_time": start_time, "end_time": end_time}


def is_in_maintenance(monitor_id: str) -> dict | None:
    """Check if a monitor is currently in a maintenance window."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT * FROM maintenance_windows
           WHERE monitor_id = ? AND start_time <= datetime('now') AND end_time > datetime('now')
           ORDER BY start_time DESC LIMIT 1""",
        (monitor_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_maintenance_windows(monitor_id: str | None = None) -> list[dict]:
    conn = _get_conn()
    if monitor_id:
        rows = conn.execute(
            "SELECT * FROM maintenance_windows WHERE monitor_id=? ORDER BY start_time DESC",
            (monitor_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM maintenance_windows ORDER BY start_time DESC LIMIT 100"
        ).fetchall()
    return _rows_to_list(rows)


def delete_maintenance_window(mw_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM maintenance_windows WHERE id=?", (mw_id,))
    conn.commit()


def update_monitor_ssl_expiry(monitor_id: str, expiry_date: str):
    """Update the SSL certificate expiry date for a monitor."""
    conn = _get_conn()
    conn.execute(
        "UPDATE monitors SET ssl_expiry=?, updated_at=? WHERE id=?",
        (expiry_date, _now(), monitor_id),
    )
    conn.commit()


# ── Performance History ────────────────────────────────────────────────────

def insert_performance_record(
    monitor_id: str, cpu_percent: float | None = None,
    ram_percent: float | None = None, disk_percent: float | None = None,
    disk_detail: list | None = None, extra: dict | None = None,
):
    """Store a performance snapshot from an agent heartbeat."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO performance_history
           (id, monitor_id, recorded_at, cpu_percent, ram_percent, disk_percent, disk_detail, extra)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (_uuid(), monitor_id, _now(), cpu_percent, ram_percent, disk_percent,
         json.dumps(disk_detail or []), json.dumps(extra or {})),
    )
    conn.commit()


def get_performance_history(monitor_id: str, limit: int = 60) -> list[dict]:
    """Get recent performance history for a monitor."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT * FROM performance_history
           WHERE monitor_id = ? ORDER BY recorded_at DESC LIMIT ?""",
        (monitor_id, limit),
    ).fetchall()
    return list(reversed(_rows_to_list(rows)))


def cleanup_old_performance(days: int = 30):
    """Remove performance records older than N days."""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM performance_history WHERE recorded_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()


# ── Remote Commands ────────────────────────────────────────────────────────

def create_remote_command(monitor_id: str, command: str) -> dict:
    """Queue a command for an agent to execute."""
    conn = _get_conn()
    cmd_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO remote_commands (id, monitor_id, command, status, created_at)
           VALUES (?, ?, ?, 'pending', ?)""",
        (cmd_id, monitor_id, command, now),
    )
    conn.commit()
    return {"id": cmd_id, "monitor_id": monitor_id, "command": command,
            "status": "pending", "created_at": now}


def get_pending_commands(monitor_id: str) -> list[dict]:
    """Get all pending commands for a monitor (agent polls this)."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT * FROM remote_commands
           WHERE monitor_id = ? AND status = 'pending'
           ORDER BY created_at ASC""",
        (monitor_id,),
    ).fetchall()
    return _rows_to_list(rows)


def update_command_result(cmd_id: str, output: str, exit_code: int, status: str = "completed"):
    """Agent reports back the result of a command."""
    conn = _get_conn()
    now = _now()
    conn.execute(
        """UPDATE remote_commands
           SET status=?, output=?, exit_code=?, completed_at=?
           WHERE id=?""",
        (status, output, exit_code, now, cmd_id),
    )
    conn.commit()


def mark_command_started(cmd_id: str):
    """Mark a command as started by the agent."""
    conn = _get_conn()
    conn.execute(
        "UPDATE remote_commands SET status='running', started_at=? WHERE id=?",
        (_now(), cmd_id),
    )
    conn.commit()


def get_command_history(monitor_id: str, limit: int = 50) -> list[dict]:
    """Get recent command history for a monitor."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT * FROM remote_commands
           WHERE monitor_id = ? ORDER BY created_at DESC LIMIT ?""",
        (monitor_id, limit),
    ).fetchall()
    return _rows_to_list(rows)


def get_command(cmd_id: str) -> dict | None:
    """Get a single command by ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM remote_commands WHERE id = ?", (cmd_id,)
    ).fetchone()
    return _row_to_dict(row)


# ── Audit / Activity Log ──────────────────────────────────────────────────

def log_audit(action: str, target_type: str = "", target_name: str = "",
              monitor_id: str = "", detail: str = "", user: str = "admin",
              ip_address: str = ""):
    """Log an activity for audit trail."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO audit_log (id, timestamp, user, action, target_type, target_name,
           monitor_id, detail, ip_address)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_uuid(), _now(), user, action, target_type, target_name,
         monitor_id or None, detail, ip_address),
    )
    conn.commit()


def get_audit_log(limit: int = 100, monitor_id: str = "") -> list[dict]:
    """Get recent audit log entries."""
    conn = _get_conn()
    if monitor_id:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE monitor_id=? ORDER BY timestamp DESC LIMIT ?",
            (monitor_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return _rows_to_list(rows)


# ── Server File Storage ───────────────────────────────────────────────────

def create_server_file(filename: str, original_name: str, size: int,
                       mime_type: str = "application/octet-stream",
                       description: str = "", uploaded_by: str = "admin") -> dict:
    """Record a file upload."""
    conn = _get_conn()
    file_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO server_files (id, filename, original_name, size, mime_type,
           uploaded_by, description, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, filename, original_name, size, mime_type, uploaded_by, description, now),
    )
    conn.commit()
    return {"id": file_id, "filename": filename, "original_name": original_name,
            "size": size, "created_at": now}


def list_server_files(limit: int = 100) -> list[dict]:
    """List uploaded files."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM server_files ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return _rows_to_list(rows)


def get_server_file(file_id: str) -> dict | None:
    """Get a single file record."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM server_files WHERE id=?", (file_id,)).fetchone()
    return _row_to_dict(row)


def increment_download_count(file_id: str):
    conn = _get_conn()
    conn.execute("UPDATE server_files SET download_count = download_count + 1 WHERE id=?", (file_id,))
    conn.commit()


def delete_server_file(file_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM server_files WHERE id=?", (file_id,))
    conn.commit()


# ── Agent Messages ────────────────────────────────────────────────────────

def create_agent_message(monitor_id: str, message: str, msg_type: str = "info") -> dict:
    """Queue a message for display on the remote agent."""
    conn = _get_conn()
    msg_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO agent_messages (id, monitor_id, message, msg_type, status, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?)""",
        (msg_id, monitor_id, message, msg_type, now),
    )
    conn.commit()
    return {"id": msg_id, "monitor_id": monitor_id, "message": message, "status": "pending"}


def get_pending_messages(monitor_id: str) -> list[dict]:
    """Get pending messages for an agent."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_messages WHERE monitor_id=? AND status='pending' ORDER BY created_at",
        (monitor_id,),
    ).fetchall()
    return _rows_to_list(rows)


def mark_message_delivered(msg_id: str):
    conn = _get_conn()
    conn.execute(
        "UPDATE agent_messages SET status='delivered', delivered_at=? WHERE id=?",
        (_now(), msg_id),
    )
    conn.commit()


def get_message_history(monitor_id: str, limit: int = 50) -> list[dict]:
    """Get message history for an agent."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_messages WHERE monitor_id=? ORDER BY created_at DESC LIMIT ?",
        (monitor_id, limit),
    ).fetchall()
    return _rows_to_list(rows)
