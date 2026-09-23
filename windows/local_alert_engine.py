"""
Tech Sentinel Monitor — Local Alert Engine & Dispatcher
========================================================
Evaluates probe results for alert conditions and sends notifications
via Email, SMS (email gateway), Windows toast, and webhooks.

By REGTeches / Ronald Goodchild
"""

import json
import logging
import os
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("ts.alerts")

# ── Alert State Tracking ────────────────────────────────────────────────────
# Tracks which monitors are currently in alert state to avoid spam
# and to detect recovery events.

_alert_state: dict[str, dict] = {}  # monitor_id -> {"alerted_at": ..., "failures": ...}
_alert_lock = threading.Lock()

# SMS email gateways for major US carriers
SMS_GATEWAYS = {
    "xfinity":    "{number}@vtext.com",
    "comcast":    "{number}@vtext.com",
    "verizon":    "{number}@vtext.com",
    "att":        "{number}@txt.att.net",
    "tmobile":    "{number}@tmomail.net",
    "sprint":     "{number}@messaging.sprintpcs.com",
    "metro":      "{number}@mymetropcs.com",
    "cricket":    "{number}@sms.cricketwireless.net",
    "boost":      "{number}@sms.myboostmobile.com",
    "uscellular": "{number}@email.uscc.net",
    "google_fi":  "{number}@msg.fi.google.com",
    "mint":       "{number}@mailmymobile.net",
    "visible":    "{number}@vtext.com",
}

# SMTP connection timeout
SMTP_TIMEOUT = 15


class AlertConfig:
    """Alert notification settings — loaded/saved to a JSON config file."""

    def __init__(self):
        self.enabled = True
        self.threshold = 3  # consecutive failures before alerting

        # Email (SMTP)
        self.email_enabled = False
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.smtp_user = ""
        self.smtp_password = ""  # App password for Gmail
        self.email_to = ""       # Recipient email

        # SMS via email gateway
        self.sms_enabled = False
        self.sms_phone = ""      # 10-digit phone number
        self.sms_carrier = "xfinity"

        # Windows desktop notifications
        self.toast_enabled = True

        # Webhook (generic HTTP POST)
        self.webhook_enabled = False
        self.webhook_url = ""

        # Cooldown: don't re-alert for same monitor within N minutes
        self.cooldown_minutes = 15

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "email_enabled": self.email_enabled,
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "smtp_user": self.smtp_user,
            "smtp_password": self.smtp_password,
            "email_to": self.email_to,
            "sms_enabled": self.sms_enabled,
            "sms_phone": self.sms_phone,
            "sms_carrier": self.sms_carrier,
            "toast_enabled": self.toast_enabled,
            "webhook_enabled": self.webhook_enabled,
            "webhook_url": self.webhook_url,
            "cooldown_minutes": self.cooldown_minutes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AlertConfig":
        cfg = cls()
        for key, val in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, val)
        return cfg

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Alert config saved to %s", path)

    @classmethod
    def load(cls, path: str) -> "AlertConfig":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        return cls()


# ── Global config instance ──────────────────────────────────────────────────

_config = AlertConfig()
_config_path = ""


def init_alert_config(config_dir: str) -> AlertConfig:
    """Load or create alert config in the given directory."""
    global _config, _config_path
    _config_path = os.path.join(config_dir, "alert_config.json")
    _config = AlertConfig.load(_config_path)
    logger.info("Alert config loaded (email=%s, sms=%s, toast=%s, webhook=%s)",
                _config.email_enabled, _config.sms_enabled,
                _config.toast_enabled, _config.webhook_enabled)
    return _config


def get_alert_config() -> AlertConfig:
    return _config


def save_alert_config():
    if _config_path:
        _config.save(_config_path)


# ── Alert Evaluation ────────────────────────────────────────────────────────

def evaluate_probe_result(monitor_id: str, result: dict):
    """Called after every probe. Evaluates whether to fire an alert or recovery."""
    if not _config.enabled:
        return

    # Skip alerting during maintenance windows (but still record data)
    if result.get("_maintenance"):
        logger.debug("Monitor %s in maintenance window, skipping alerts", monitor_id[:8])
        return

    status = result.get("status", "unknown")

    # Check SSL certificate expiry
    ssl_expiry = result.get("ssl_expiry")
    if ssl_expiry:
        _check_ssl_alert(monitor_id, ssl_expiry)

    with _alert_lock:
        was_alerting = monitor_id in _alert_state

    if status != "up":
        _handle_failure(monitor_id, result)
    elif was_alerting:
        _handle_recovery(monitor_id, result)


def _check_ssl_alert(monitor_id: str, ssl_expiry: str):
    """Alert if SSL certificate expires within 14 days."""
    try:
        from datetime import datetime as dt
        expiry_dt = dt.fromisoformat(ssl_expiry)
        days_left = (expiry_dt - dt.now()).days
        if days_left <= 14:
            from windows.local_database import get_monitor
            monitor = get_monitor(monitor_id)
            if monitor:
                ssl_key = f"ssl_{monitor_id}"
                with _alert_lock:
                    if ssl_key in _alert_state:
                        return  # Already alerted about this cert
                    _alert_state[ssl_key] = {"alerted_at": time.time(), "failures": 0}
                _dispatch_alert(
                    event="ssl_expiry",
                    monitor=monitor,
                    failures=days_left,
                    error=f"SSL certificate expires in {days_left} days ({ssl_expiry[:10]})",
                )
    except Exception as e:
        logger.debug("SSL check error: %s", e)


def _handle_failure(monitor_id: str, result: dict):
    """Check consecutive failures and fire alert if threshold breached."""
    from windows.local_database import get_consecutive_failures, get_monitor

    failures = get_consecutive_failures(monitor_id)

    if failures < _config.threshold:
        logger.debug("Monitor %s: %d failures (threshold=%d), waiting...",
                      monitor_id[:8], failures, _config.threshold)
        return  # Not enough failures yet

    logger.warning("🚨 Monitor %s: %d consecutive failures >= threshold %d",
                    monitor_id[:8], failures, _config.threshold)

    with _alert_lock:
        state = _alert_state.get(monitor_id)
        now = time.time()

        if state:
            # Already alerted — check cooldown
            elapsed_min = (now - state["alerted_at"]) / 60
            if elapsed_min < _config.cooldown_minutes:
                return  # Within cooldown, don't re-alert
            state["alerted_at"] = now
            state["failures"] = failures
        else:
            # New alert — record incident
            _alert_state[monitor_id] = {"alerted_at": now, "failures": failures}

    monitor = get_monitor(monitor_id)
    if not monitor:
        return

    # Log incident to database
    try:
        from windows.local_database import create_incident
        channels = []
        if _config.email_enabled: channels.append("email")
        if _config.sms_enabled: channels.append("sms")
        if _config.toast_enabled: channels.append("desktop")
        if _config.webhook_enabled: channels.append("webhook")
        create_incident(
            monitor_id=monitor_id,
            monitor_name=monitor.get("name", "Unknown"),
            event="down",
            failures=failures,
            error=result.get("error", ""),
            channels_notified=channels,
        )
    except Exception as e:
        logger.error("Failed to log incident: %s", e)

    _dispatch_alert(
        event="down",
        monitor=monitor,
        failures=failures,
        error=result.get("error", ""),
    )


def _handle_recovery(monitor_id: str, result: dict):
    """Monitor recovered — send recovery notification and clear state."""
    from windows.local_database import get_monitor, resolve_incident

    with _alert_lock:
        state = _alert_state.pop(monitor_id, None)

    if not state:
        return

    monitor = get_monitor(monitor_id)
    if not monitor:
        return

    down_minutes = (time.time() - state["alerted_at"]) / 60

    # Resolve incident in database
    try:
        resolve_incident(monitor_id)
    except Exception as e:
        logger.error("Failed to resolve incident: %s", e)

    _dispatch_alert(
        event="recovery",
        monitor=monitor,
        failures=state["failures"],
        error=f"Was down for ~{down_minutes:.0f} minutes",
    )


# ── Dispatch ────────────────────────────────────────────────────────────────

def _dispatch_alert(event: str, monitor: dict, failures: int, error: str):
    """Send alert through all enabled channels (in a background thread to not block probes)."""
    name = monitor.get("name", "?")
    logger.info("🔔 DISPATCHING %s alert for: %s (failures=%d, email=%s, sms=%s, toast=%s)",
                event.upper(), name, failures,
                _config.email_enabled, _config.sms_enabled, _config.toast_enabled)
    threading.Thread(
        target=_dispatch_alert_sync,
        args=(event, monitor, failures, error),
        daemon=True,
        name="alert-dispatch",
    ).start()


def _dispatch_alert_sync(event: str, monitor: dict, failures: int, error: str):
    """Synchronous dispatch to all enabled channels."""
    name = monitor.get("name", "Unknown")
    target = monitor.get("target", "")
    mtype = monitor.get("monitor_type", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if event == "ssl_expiry":
        subject = f"🔐 SSL EXPIRING: {name}"
        short_msg = f"🔐 SSL: {name} cert expires in {failures} days!"
        detail = (
            f"Monitor: {name}\n"
            f"Target: {target}\n"
            f"Warning: {error}\n"
            f"Time: {now}\n"
            f"Action: Renew the SSL certificate ASAP\n"
        )
    elif event == "down":
        subject = f"🚨 DOWN: {name}"
        short_msg = f"🚨 DOWN: {name} ({mtype}://{target}) - {failures} failures"
        detail = (
            f"Monitor: {name}\n"
            f"Type: {mtype.upper()}\n"
            f"Target: {target}\n"
            f"Status: DOWN ({failures} consecutive failures)\n"
            f"Error: {error}\n"
            f"Time: {now}\n"
        )
    else:
        subject = f"✅ RECOVERED: {name}"
        short_msg = f"✅ UP: {name} ({mtype}://{target}) is back online"
        detail = (
            f"Monitor: {name}\n"
            f"Type: {mtype.upper()}\n"
            f"Target: {target}\n"
            f"Status: RECOVERED\n"
            f"Note: {error}\n"
            f"Time: {now}\n"
        )

    logger.info("ALERT [%s] %s", event.upper(), short_msg)

    # ── Email ────────────────────────────────────────────────────────────
    if _config.email_enabled and _config.email_to and _config.smtp_user:
        try:
            _send_email(subject, detail)
            logger.info("📧 Email alert sent to %s", _config.email_to)
        except Exception as e:
            logger.error("📧 Email alert failed: %s", e)

    # ── SMS ──────────────────────────────────────────────────────────────
    if _config.sms_enabled and _config.sms_phone:
        try:
            _send_sms(short_msg)
            logger.info("📱 SMS alert sent to %s", _config.sms_phone)
        except Exception as e:
            logger.error("📱 SMS alert failed: %s", e)

    # ── Windows Toast ────────────────────────────────────────────────────
    if _config.toast_enabled:
        try:
            _send_toast(subject, short_msg)
        except Exception as e:
            logger.error("🔔 Toast notification failed: %s", e)

    # ── Webhook ──────────────────────────────────────────────────────────
    if _config.webhook_enabled and _config.webhook_url:
        try:
            _send_webhook(event, monitor, failures, error, now)
            logger.info("🔗 Webhook alert sent to %s", _config.webhook_url)
        except Exception as e:
            logger.error("🔗 Webhook alert failed: %s", e)


# ── Channel Implementations ─────────────────────────────────────────────────

def _send_email(subject: str, body: str):
    """Send email via SMTP."""
    logger.info("📧 Connecting to %s:%s as %s ...", _config.smtp_server, _config.smtp_port, _config.smtp_user)

    msg = MIMEMultipart("alternative")
    msg["From"] = _config.smtp_user
    msg["To"] = _config.email_to
    msg["Subject"] = subject

    html_body = f"""<html><body style="font-family:Segoe UI,sans-serif;background:#0f1117;color:#e1e4ed;padding:2rem;">
    <div style="max-width:500px;margin:0 auto;background:#1a1d27;border-radius:12px;padding:1.5rem;border:1px solid #333750;">
        <h2 style="color:#3b82f6;margin-top:0;">🛡️ Tech Sentinel Monitor</h2>
        <pre style="background:#222636;padding:1rem;border-radius:8px;color:#e1e4ed;white-space:pre-wrap;">{body}</pre>
        <p style="color:#8b8fa3;font-size:0.85rem;margin-top:1rem;">
            Sent by Tech Sentinel Monitor — REGTeches
        </p>
    </div>
    </body></html>"""

    msg.attach(MIMEText(body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    server = smtplib.SMTP(_config.smtp_server, _config.smtp_port, timeout=SMTP_TIMEOUT)
    try:
        server.ehlo()
        server.starttls()
        server.ehlo()
        logger.info("📧 Logging in as %s ...", _config.smtp_user)
        server.login(_config.smtp_user, _config.smtp_password)
        logger.info("📧 Sending email to %s ...", _config.email_to)
        server.send_message(msg)
        logger.info("📧 Email sent successfully!")
    finally:
        server.quit()


def _send_sms(message: str):
    """Send SMS via carrier email gateway."""
    carrier = _config.sms_carrier.lower().replace(" ", "").replace("-", "")
    gateway_template = SMS_GATEWAYS.get(carrier)
    if not gateway_template:
        raise ValueError(f"Unknown carrier: {carrier} (supported: {', '.join(SMS_GATEWAYS.keys())})")

    phone = _config.sms_phone.replace("-", "").replace("(", "").replace(")", "").replace(" ", "").replace("+1", "")
    if len(phone) != 10 or not phone.isdigit():
        raise ValueError(f"Phone number must be 10 digits, got: '{phone}'")

    sms_addr = gateway_template.format(number=phone)
    logger.info("📱 Sending SMS to %s via %s gateway (%s) ...", phone, carrier, sms_addr)

    msg = MIMEText(message[:160])  # SMS limit
    msg["From"] = _config.smtp_user
    msg["To"] = sms_addr
    msg["Subject"] = "Alert"

    server = smtplib.SMTP(_config.smtp_server, _config.smtp_port, timeout=SMTP_TIMEOUT)
    try:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(_config.smtp_user, _config.smtp_password)
        server.send_message(msg)
        logger.info("📱 SMS email sent to %s", sms_addr)
    finally:
        server.quit()


def _send_toast(title: str, message: str):
    """Send a Windows 10/11 toast notification."""
    try:
        # Try using winotify (lightweight, no extra deps needed at runtime)
        from winotify import Notification
        toast = Notification(
            app_id="Tech Sentinel Monitor",
            title=title,
            msg=message,
            duration="long",
        )
        toast.set_audio(sound=None, loop=False)
        toast.show()
        return
    except ImportError:
        pass

    # Fallback: PowerShell toast (works on any Windows 10/11, no pip install)
    import subprocess
    ps_script = (
        f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, '
        f'ContentType = WindowsRuntime] > $null; '
        f'$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1); '
        f'$text = $xml.GetElementsByTagName("text"); '
        f'$text[0].AppendChild($xml.CreateTextNode("{title.replace(chr(34), "")}")) > $null; '
        f'$text[1].AppendChild($xml.CreateTextNode("{message.replace(chr(34), "")}")) > $null; '
        f'$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Tech Sentinel"); '
        f'$notifier.Show([Windows.UI.Notifications.ToastNotification]::new($xml))'
    )
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception as e:
        # Last resort: winsound beep + log
        logger.warning("Toast failed, beeping instead: %s", e)
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


def _send_webhook(event: str, monitor: dict, failures: int, error: str, timestamp: str):
    """Send a JSON webhook POST."""
    import httpx

    payload = {
        "event": event,
        "monitor": {
            "id": monitor.get("id"),
            "name": monitor.get("name"),
            "type": monitor.get("monitor_type"),
            "target": monitor.get("target"),
        },
        "failures": failures,
        "error": error,
        "timestamp": timestamp,
        "source": "Tech Sentinel Monitor",
    }

    httpx.post(
        _config.webhook_url,
        json=payload,
        timeout=10,
        headers={"Content-Type": "application/json", "User-Agent": "TechSentinelMonitor/1.0"},
    )


# ── Test function ───────────────────────────────────────────────────────────

def send_test_alert() -> dict:
    """Send a test notification through all enabled channels.
    Returns a dict of channel -> "ok" or error message.
    """
    results = {}
    subject = "🚨 TEST: Down Alert"
    short_msg = "🚨 TEST: Test Monitor (ping://192.168.1.1) - This is a test alert"
    detail = (
        "Monitor: Test Monitor\n"
        "Type: PING\n"
        "Target: 192.168.1.1\n"
        "Status: DOWN (3 consecutive failures)\n"
        "Error: This is a test alert from Tech Sentinel Monitor\n"
        "Time: NOW\n"
    )
    fake_monitor = {"id": "test-000", "name": "Test Monitor", "monitor_type": "ping", "target": "192.168.1.1"}

    # ── Toast ────────────────────────────────────────────────────────
    if _config.toast_enabled:
        try:
            _send_toast(subject, short_msg)
            results["🔔 Desktop"] = "ok"
        except Exception as e:
            results["🔔 Desktop"] = str(e)
    else:
        results["🔔 Desktop"] = "disabled"

    # ── Email ────────────────────────────────────────────────────────
    if _config.email_enabled:
        if not _config.smtp_user:
            results["📧 Email"] = "SMTP User (email) is empty"
        elif not _config.smtp_password:
            results["📧 Email"] = "SMTP Password is empty"
        elif not _config.email_to:
            results["📧 Email"] = "Send Alerts To is empty"
        else:
            try:
                _send_email(subject, detail)
                results["📧 Email"] = "ok"
            except smtplib.SMTPAuthenticationError as e:
                results["📧 Email"] = f"Login failed — check password (use App Password for Gmail): {e.smtp_error}"
            except smtplib.SMTPConnectError as e:
                results["📧 Email"] = f"Can't connect to {_config.smtp_server}:{_config.smtp_port}: {e}"
            except TimeoutError:
                results["📧 Email"] = f"Timeout connecting to {_config.smtp_server}:{_config.smtp_port}"
            except Exception as e:
                results["📧 Email"] = f"{type(e).__name__}: {e}"
    else:
        results["📧 Email"] = "disabled"

    # ── SMS ──────────────────────────────────────────────────────────
    if _config.sms_enabled:
        if not _config.sms_phone:
            results["📱 SMS"] = "Phone number is empty"
        elif not _config.smtp_user or not _config.smtp_password:
            results["📱 SMS"] = "SMS uses email gateway — fill in SMTP User + Password"
        else:
            try:
                _send_sms(short_msg)
                results["📱 SMS"] = "ok"
            except smtplib.SMTPAuthenticationError as e:
                results["📱 SMS"] = f"Login failed — use App Password for Gmail: {e.smtp_error}"
            except ValueError as e:
                results["📱 SMS"] = str(e)
            except TimeoutError:
                results["📱 SMS"] = f"Timeout connecting to {_config.smtp_server}:{_config.smtp_port}"
            except Exception as e:
                results["📱 SMS"] = f"{type(e).__name__}: {e}"
    else:
        results["📱 SMS"] = "disabled"

    # ── Webhook ──────────────────────────────────────────────────────
    if _config.webhook_enabled:
        if not _config.webhook_url:
            results["🔗 Webhook"] = "Webhook URL is empty"
        else:
            try:
                _send_webhook("down", fake_monitor, 3, "Test alert", "NOW")
                results["🔗 Webhook"] = "ok"
            except Exception as e:
                results["🔗 Webhook"] = f"{type(e).__name__}: {e}"
    else:
        results["🔗 Webhook"] = "disabled"

    # Log summary
    for ch, status in results.items():
        if status == "ok":
            logger.info("✅ %s — sent successfully", ch)
        elif status == "disabled":
            logger.info("⏭️ %s — disabled, skipped", ch)
        else:
            logger.error("❌ %s — FAILED: %s", ch, status)

    return results
