"""
Tech Sentinel Monitor — Local Probe Worker (threaded)
Runs probes using threads instead of Redis Streams.
Schedules active monitors on a recurring interval.
"""

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from windows.local_database import (
    list_all_active_monitors, insert_check_result,
    get_consecutive_failures, list_alert_channels, get_monitor,
)
from windows.local_queue import enqueue_job, dequeue_job, mark_done, mark_processed, mark_failed

logger = logging.getLogger("ts.local_worker")


# ── Probes (synchronous wrappers around async probes) ────────────────────────

def _run_async(coro):
    """Run an async coroutine in a new event loop (for threads)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _check_ssl_expiry(target: str) -> str | None:
    """Check SSL certificate expiry for HTTPS targets. Returns ISO date or None."""
    import ssl
    from urllib.parse import urlparse

    try:
        parsed = urlparse(target)
        if parsed.scheme != "https":
            return None
        host = parsed.hostname
        port = parsed.port or 443
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(ssl.socket.socket(), server_hostname=host) as s:
            s.settimeout(5)
            s.connect((host, port))
            cert = s.getpeercert()
            if cert and "notAfter" in cert:
                from datetime import datetime as dt
                expiry = dt.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                return expiry.isoformat()
    except Exception:
        pass
    return None


def run_http_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    import httpx
    config = json.loads(config_str) if isinstance(config_str, str) else config_str
    method = config.get("method", "GET").upper()
    expected_status = config.get("expected_status", 200)
    body_contains = config.get("body_contains", None)

    start = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, verify=False) as client:
            resp = client.request(method, target)
            elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code != expected_status:
                return {"status": "down", "response_time_ms": elapsed_ms,
                        "status_code": resp.status_code,
                        "error": f"Expected {expected_status}, got {resp.status_code}"}

            if body_contains and body_contains not in resp.text:
                return {"status": "down", "response_time_ms": elapsed_ms,
                        "status_code": resp.status_code,
                        "error": f"Body does not contain '{body_contains}'"}

            # Check SSL certificate expiry in background
            ssl_expiry = _check_ssl_expiry(target)

            result = {"status": "up", "response_time_ms": elapsed_ms,
                      "status_code": resp.status_code, "error": None}
            if ssl_expiry:
                result["ssl_expiry"] = ssl_expiry
            return result
    except httpx.TimeoutException:
        return {"status": "timeout", "response_time_ms": (time.monotonic() - start) * 1000,
                "status_code": None, "error": "Connection timed out"}
    except Exception as e:
        return {"status": "down", "response_time_ms": (time.monotonic() - start) * 1000,
                "status_code": None, "error": str(e)}


def run_tcp_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    import socket
    try:
        if ":" not in target:
            return {"status": "down", "response_time_ms": 0, "status_code": None,
                    "error": "Target must be in host:port format"}
        host, port_str = target.rsplit(":", 1)
        port = int(port_str)
    except ValueError:
        return {"status": "down", "response_time_ms": 0, "status_code": None,
                "error": f"Invalid port in target: {target}"}

    start = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        elapsed_ms = (time.monotonic() - start) * 1000
        sock.close()
        return {"status": "up", "response_time_ms": elapsed_ms, "status_code": None, "error": None}
    except socket.timeout:
        return {"status": "timeout", "response_time_ms": (time.monotonic() - start) * 1000,
                "status_code": None, "error": f"TCP connection to {host}:{port} timed out"}
    except Exception as e:
        return {"status": "down", "response_time_ms": (time.monotonic() - start) * 1000,
                "status_code": None, "error": str(e)}


def run_ping_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    import subprocess
    import re

    # CREATE_NO_WINDOW prevents console windows from flashing on screen
    CREATE_NO_WINDOW = 0x08000000

    start = time.monotonic()
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout * 1000), target],
            capture_output=True, text=True, timeout=timeout + 5,
            creationflags=CREATE_NO_WINDOW,
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        if result.returncode == 0:
            # Parse RTT from Windows ping output
            match = re.search(r"Average\s*=\s*(\d+)ms", result.stdout)
            rtt = float(match.group(1)) if match else elapsed_ms
            return {"status": "up", "response_time_ms": rtt, "status_code": None, "error": None}
        else:
            return {"status": "down", "response_time_ms": elapsed_ms,
                    "status_code": None, "error": "Host unreachable"}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "response_time_ms": (time.monotonic() - start) * 1000,
                "status_code": None, "error": "Ping timed out"}
    except Exception as e:
        return {"status": "down", "response_time_ms": (time.monotonic() - start) * 1000,
                "status_code": None, "error": str(e)}


def run_heartbeat_probe(target: str, timeout: int, config_str: str = "{}",
                        monitor_id: str = "") -> dict:
    """Check if a heartbeat was received recently.

    For heartbeat monitors, the agent POSTs results using monitor_id,
    so we must look up results by monitor_id (not target).

    Grace period = 3x the monitor's interval (default 60s → 180s grace).
    This avoids false "down" flapping when the agent heartbeat is slightly
    delayed or the probe runs between heartbeats.
    """
    from windows.local_database import get_recent_results, get_monitor

    lookup_id = monitor_id or target
    results = get_recent_results(lookup_id, limit=1)
    if not results:
        return {"status": "down", "response_time_ms": 0, "status_code": None,
                "error": "No heartbeat received yet"}

    from datetime import datetime, timezone
    last = results[0]
    try:
        last_time = datetime.fromisoformat(last["checked_at"])
    except (ValueError, TypeError):
        last_time = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    age = (now - last_time).total_seconds()

    # Grace = 3x the monitor interval (agents heartbeat every 60s,
    # so 180s grace prevents false downs between heartbeats)
    monitor = get_monitor(lookup_id) if lookup_id else None
    interval = 60
    if monitor:
        interval = monitor.get("interval_seconds", 60) or 60
    grace = max(interval * 3, 180)  # At least 180s grace

    if age > grace:
        return {"status": "down", "response_time_ms": 0, "status_code": None,
                "error": f"Last heartbeat {int(age)}s ago (grace: {grace}s)"}

    return {"status": "up", "response_time_ms": 0, "status_code": None, "error": None}


PROBE_MAP = {
    "http": run_http_probe,
    "tcp": run_tcp_probe,
    "ping": run_ping_probe,
    "heartbeat": run_heartbeat_probe,
}


# ── Worker ───────────────────────────────────────────────────────────────────

class LocalProbeWorker:
    """Threaded probe worker that processes jobs and schedules monitors."""

    def __init__(self, concurrency: int = 5, on_result=None):
        self._running = False
        self._concurrency = concurrency
        self._executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="probe")
        self._scheduler_thread: threading.Thread | None = None
        self._consumer_thread: threading.Thread | None = None
        self._on_result = on_result  # Callback: (monitor_id, result_dict)
        self.total_checks = 0
        self.checks_up = 0
        self.checks_down = 0

    def start(self):
        self._running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True, name="probe-scheduler")
        self._consumer_thread = threading.Thread(target=self._consumer_loop, daemon=True, name="probe-consumer")
        self._scheduler_thread.start()
        self._consumer_thread.start()
        logger.info("Local probe worker started (concurrency=%d)", self._concurrency)

    def stop(self):
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        if self._consumer_thread:
            self._consumer_thread.join(timeout=5)
        self._executor.shutdown(wait=False)
        logger.info("Local probe worker stopped")

    def _scheduler_loop(self):
        """Periodically enqueue active monitors for probing."""
        while self._running:
            try:
                monitors = list_all_active_monitors()
                for m in monitors:
                    enqueue_job({
                        "monitor_id": m["id"],
                        "tenant_id": m["tenant_id"],
                        "monitor_type": m["monitor_type"],
                        "target": m["target"],
                        "interval_seconds": str(m["interval_seconds"]),
                        "timeout_seconds": str(m["timeout_seconds"]),
                        "config": m.get("config", "{}"),
                    })
            except Exception as e:
                logger.error("Scheduler error: %s", e)

            # Sleep for the minimum interval (check every 30s)
            for _ in range(30):
                if not self._running:
                    return
                time.sleep(1)

    def _consumer_loop(self):
        """Consume jobs from the queue and execute probes."""
        while self._running:
            job = dequeue_job(timeout=2.0)
            if job is None:
                continue
            self._executor.submit(self._execute_probe, job)

    def _execute_probe(self, job: dict):
        monitor_id = job.get("monitor_id", "")
        monitor_type = job.get("monitor_type", "")
        target = job.get("target", "")
        timeout = int(job.get("timeout_seconds", "10"))
        config = job.get("config", "{}")

        # Check maintenance window — skip alerting but still probe
        in_maintenance = False
        try:
            from windows.local_database import is_in_maintenance
            mw = is_in_maintenance(monitor_id)
            if mw:
                in_maintenance = True
        except Exception:
            pass

        probe_fn = PROBE_MAP.get(monitor_type)
        if not probe_fn:
            logger.error("Unknown probe type: %s", monitor_type)
            mark_done()
            return

        result = None
        is_heartbeat = (monitor_type == "heartbeat")
        try:
            if is_heartbeat:
                # Pass monitor_id so heartbeat probe can look up results correctly
                result = probe_fn(target, timeout, config, monitor_id=monitor_id)
            else:
                result = probe_fn(target, timeout, config)

            if not is_heartbeat:
                # Heartbeat monitors get their results inserted by the agent's
                # heartbeat API endpoint — the probe only checks recency, it
                # should NOT insert its own check results (that caused the
                # flip-flop between up/down every 30s).
                insert_check_result(
                    monitor_id=monitor_id,
                    status=result["status"],
                    response_time_ms=result.get("response_time_ms"),
                    status_code=result.get("status_code"),
                    error=result.get("error"),
                )

            # Save SSL expiry if returned
            if result.get("ssl_expiry"):
                try:
                    from windows.local_database import update_monitor_ssl_expiry
                    update_monitor_ssl_expiry(monitor_id, result["ssl_expiry"])
                except Exception:
                    pass

            self.total_checks += 1
            if result["status"] == "up":
                self.checks_up += 1
            else:
                self.checks_down += 1

            mark_processed()
            logger.info("Probe %s://%s -> %s (%.1fms)",
                        monitor_type, target, result["status"],
                        result.get("response_time_ms", 0))

        except Exception as e:
            logger.error("Probe error for %s: %s", monitor_id, e)
            result = {"status": "down", "error": str(e)}
            mark_failed()

        # Broadcast status update via WebSocket (non-blocking)
        # Skip broadcasting for heartbeat monitors — their status comes from
        # the heartbeat API endpoint, not the probe. Broadcasting probe results
        # causes the status page to flip-flop between up/down.
        try:
            if result and not is_heartbeat:
                self._broadcast_ws(monitor_id, result)
        except Exception:
            pass

        # Alert evaluation runs OUTSIDE the try/except so errors don't get swallowed
        # For heartbeat monitors, only alert if probe says "down" (missed heartbeats)
        try:
            if self._on_result and result:
                if in_maintenance:
                    result["_maintenance"] = True
                if is_heartbeat and result.get("status") == "up":
                    pass  # Don't send "up" from probe — heartbeat API handles it
                else:
                    self._on_result(monitor_id, result)
        except Exception as e:
            logger.error("Alert callback error for %s: %s", monitor_id, e, exc_info=True)
        finally:
            mark_done()

    def _broadcast_ws(self, monitor_id: str, result: dict):
        """Send status update to all WebSocket clients."""
        try:
            import asyncio
            from windows.local_api import broadcast_status_update
            try:
                loop = asyncio.get_running_loop()
                asyncio.ensure_future(broadcast_status_update(monitor_id, result))
            except RuntimeError:
                # No running loop — create one for this broadcast
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(broadcast_status_update(monitor_id, result))
                finally:
                    loop.close()
        except Exception as e:
            logger.debug("WebSocket broadcast skipped: %s", e)
