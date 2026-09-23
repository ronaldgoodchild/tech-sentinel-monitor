"""
Tech Sentinel Monitor — Windows Launcher GUI
============================================
Single-window tkinter app that runs the entire platform locally:
  - Control Plane API (FastAPI on :8000)
  - Probe Worker (threaded, no Redis needed)
  - Status Page (FastAPI on :8001)
  - SQLite database (no PostgreSQL needed)

Run directly:  python -m windows.launcher
Or as EXE:     TechSentinelMonitor.exe

By REGTeches / Ronald Goodchild
"""

import json
import logging
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import webbrowser
from datetime import datetime, timezone

# ── Logging Setup ────────────────────────────────────────────────────────────

LOG_BUFFER = []
LOG_LOCK = threading.Lock()


class GUILogHandler(logging.Handler):
    """Captures log records for the GUI console."""
    def emit(self, record):
        msg = self.format(record)
        with LOG_LOCK:
            LOG_BUFFER.append(msg)
            if len(LOG_BUFFER) > 2000:
                LOG_BUFFER.pop(0)


gui_handler = GUILogHandler()
gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
logging.basicConfig(level=logging.INFO, handlers=[gui_handler])
logger = logging.getLogger("ts.launcher")

# ── Color Palette ────────────────────────────────────────────────────────────

COLORS = {
    "bg_dark": "#0f1117",
    "bg_mid": "#1a1d27",
    "bg_card": "#222636",
    "bg_input": "#2a2e3f",
    "fg": "#e1e4ed",
    "fg_dim": "#8b8fa3",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "green": "#22c55e",
    "red": "#ef4444",
    "yellow": "#f59e0b",
    "orange": "#f97316",
    "border": "#333750",
}


class TechSentinelLauncher:
    """Main launcher window for Tech Sentinel Monitor."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("\U0001f6e1\ufe0f Tech Sentinel Monitor — REGTeches")
        self.root.geometry("960x720")
        self.root.minsize(800, 600)
        self.root.configure(bg=COLORS["bg_dark"])

        # State
        self.api_running = False
        self.worker_running = False
        self.api_thread: threading.Thread | None = None
        self.worker_instance = None
        self.uvicorn_server = None
        self.status_server = None
        self.db_path = ""

        # Build UI
        self._build_styles()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # Start log refresh
        self._refresh_logs()
        self._refresh_stats()

        # Handle close
        self.root.protocol("WM_DELETE_CLOSE", self._on_close)

    def _build_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background=COLORS["bg_dark"])
        style.configure("Card.TFrame", background=COLORS["bg_card"])
        style.configure("Mid.TFrame", background=COLORS["bg_mid"])

        style.configure("Dark.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["fg"], font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["fg"], font=("Segoe UI", 18, "bold"))
        style.configure("Sub.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["fg_dim"], font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=COLORS["bg_card"],
                         foreground=COLORS["fg"], font=("Segoe UI", 10))
        style.configure("CardDim.TLabel", background=COLORS["bg_card"],
                         foreground=COLORS["fg_dim"], font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=COLORS["bg_mid"],
                         foreground=COLORS["fg_dim"], font=("Segoe UI", 9))

        style.configure("Accent.TButton", background=COLORS["accent"],
                         foreground="white", font=("Segoe UI", 10, "bold"),
                         padding=(16, 8))
        style.map("Accent.TButton",
                   background=[("active", COLORS["accent_hover"]),
                               ("disabled", COLORS["bg_input"])])

        style.configure("Stop.TButton", background=COLORS["red"],
                         foreground="white", font=("Segoe UI", 10, "bold"),
                         padding=(16, 8))
        style.map("Stop.TButton",
                   background=[("active", "#dc2626"), ("disabled", COLORS["bg_input"])])

        style.configure("Link.TButton", background=COLORS["bg_card"],
                         foreground=COLORS["accent"], font=("Segoe UI", 9, "underline"),
                         padding=(8, 4))

        style.configure("Dark.TNotebook", background=COLORS["bg_dark"])
        style.configure("Dark.TNotebook.Tab", background=COLORS["bg_mid"],
                         foreground=COLORS["fg_dim"], padding=(12, 6),
                         font=("Segoe UI", 10))
        style.map("Dark.TNotebook.Tab",
                   background=[("selected", COLORS["accent"])],
                   foreground=[("selected", "white")])

    def _build_header(self):
        header = ttk.Frame(self.root, style="Dark.TFrame")
        header.pack(fill="x", padx=20, pady=(15, 5))

        ttk.Label(header, text="\U0001f6e1\ufe0f Tech Sentinel Monitor",
                  style="Header.TLabel").pack(side="left")
        from windows.local_version_control import APP_VERSION
        ttk.Label(header, text=f"v{APP_VERSION} — Windows Standalone | REGTeches",
                  style="Sub.TLabel").pack(side="left", padx=(12, 0), pady=(6, 0))

        # Right-side buttons
        ttk.Button(header, text="\u2753 Manual",
                   style="Link.TButton", command=self._show_manual).pack(side="right", padx=(5, 0))
        ttk.Button(header, text="\u2139\ufe0f About",
                   style="Link.TButton", command=self._show_about).pack(side="right", padx=(5, 0))

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=20, pady=10)

        self._build_dashboard_tab()
        self._build_monitors_tab()
        self._build_console_tab()
        self._build_settings_tab()

    def _build_dashboard_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text=" \U0001f4ca Dashboard ")

        # ── Service Controls ─────────────────────────────────────────────
        ctrl_frame = ttk.Frame(tab, style="Card.TFrame")
        ctrl_frame.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(ctrl_frame, text="\u2699\ufe0f Service Controls",
                  style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        btn_row = ttk.Frame(ctrl_frame, style="Card.TFrame")
        btn_row.pack(fill="x", padx=15, pady=(0, 10))

        self.start_btn = ttk.Button(btn_row, text="\u25b6\ufe0f Start All Services",
                                     style="Accent.TButton", command=self._start_services)
        self.start_btn.pack(side="left", padx=(0, 10))

        self.stop_btn = ttk.Button(btn_row, text="\u23f9\ufe0f Stop All Services",
                                    style="Stop.TButton", command=self._stop_services, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 10))

        self.open_api_btn = ttk.Button(btn_row, text="\U0001f310 Open API",
                                        style="Link.TButton",
                                        command=self._open_api)
        self.open_api_btn.pack(side="left", padx=(0, 5))

        self.open_docs_btn = ttk.Button(btn_row, text="\U0001f4d6 API Docs",
                                         style="Link.TButton",
                                         command=self._open_docs)
        self.open_docs_btn.pack(side="left", padx=(0, 5))

        self.open_status_btn = ttk.Button(btn_row, text="\U0001f4ca Status Pages",
                                           style="Link.TButton",
                                           command=self._open_status)
        self.open_status_btn.pack(side="left")

        # ── Import Row ──────────────────────────────────────────────────
        import_row = ttk.Frame(ctrl_frame, style="Card.TFrame")
        import_row.pack(fill="x", padx=15, pady=(0, 10))

        self.import_noc_btn = ttk.Button(
            import_row, text="\U0001f4c2 Load NOC Config",
            style="Accent.TButton", command=self._import_noc_config)
        self.import_noc_btn.pack(side="left", padx=(0, 10))

        self.import_demo_btn = ttk.Button(
            import_row, text="\U0001f3e2 Load ACME Demo",
            style="Link.TButton", command=self._import_demo_layout)
        self.import_demo_btn.pack(side="left", padx=(0, 10))

        self.import_status = ttk.Label(import_row, text="",
                                        style="Card.TLabel", foreground=COLORS["fg_dim"])
        self.import_status.pack(side="left")

        # ── Service Status Cards ─────────────────────────────────────────
        cards_frame = ttk.Frame(tab, style="Dark.TFrame")
        cards_frame.pack(fill="x", padx=10, pady=5)

        # API Status
        self.api_card = self._make_status_card(cards_frame,
            "\U0001f4e1 Control Plane API", "Port 8000", "Stopped")
        self.api_card.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # Worker Status
        self.worker_card = self._make_status_card(cards_frame,
            "\u2699\ufe0f Probe Worker", "Threaded", "Stopped")
        self.worker_card.pack(side="left", fill="both", expand=True, padx=5)

        # Status Page
        self.status_card = self._make_status_card(cards_frame,
            "\U0001f4ca Status Page", "Port 8001", "Stopped")
        self.status_card.pack(side="left", fill="both", expand=True, padx=(5, 0))

        # ── Stats ────────────────────────────────────────────────────────
        stats_frame = ttk.Frame(tab, style="Card.TFrame")
        stats_frame.pack(fill="x", padx=10, pady=(5, 10))

        ttk.Label(stats_frame, text="\U0001f4c8 Live Statistics",
                  style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        stats_row = ttk.Frame(stats_frame, style="Card.TFrame")
        stats_row.pack(fill="x", padx=15, pady=(0, 10))

        self.stat_checks = self._make_stat_widget(stats_row, "\U0001f50d Total Checks", "0")
        self.stat_checks.pack(side="left", fill="x", expand=True)

        self.stat_up = self._make_stat_widget(stats_row, "\u2705 Up", "0")
        self.stat_up.pack(side="left", fill="x", expand=True)

        self.stat_down = self._make_stat_widget(stats_row, "\u274c Down", "0")
        self.stat_down.pack(side="left", fill="x", expand=True)

        self.stat_queue = self._make_stat_widget(stats_row, "\U0001f4e5 Queue", "0")
        self.stat_queue.pack(side="left", fill="x", expand=True)

        self.stat_db = self._make_stat_widget(stats_row, "\U0001f4be DB Size", "0 MB")
        self.stat_db.pack(side="left", fill="x", expand=True)

    def _make_status_card(self, parent, title, subtitle, status_text):
        card = ttk.Frame(parent, style="Card.TFrame")
        ttk.Label(card, text=title, style="Card.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        ttk.Label(card, text=subtitle, style="CardDim.TLabel").pack(anchor="w", padx=10)

        status_label = ttk.Label(card, text=f"\u25cf {status_text}", style="Card.TLabel")
        status_label.pack(anchor="w", padx=10, pady=(2, 8))
        card._status_label = status_label
        return card

    def _make_stat_widget(self, parent, label, value):
        frame = ttk.Frame(parent, style="Card.TFrame")
        val_lbl = ttk.Label(frame, text=value, style="Card.TLabel",
                            font=("Segoe UI", 16, "bold"))
        val_lbl.pack()
        ttk.Label(frame, text=label, style="CardDim.TLabel").pack()
        frame._value_label = val_lbl
        return frame

    def _build_monitors_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text=" \U0001f50d Monitors ")

        ttk.Label(tab, text="\U0001f50d Active Monitors",
                  style="Dark.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        # Treeview for monitors (hidden id column for lookups)
        columns = ("id", "name", "type", "target", "group", "status", "uptime_24h", "last_check", "response_ms")
        self.monitors_tree = ttk.Treeview(tab, columns=columns, show="headings", height=15)

        self.monitors_tree.heading("id", text="ID")
        self.monitors_tree.heading("name", text="Name")
        self.monitors_tree.heading("type", text="Type")
        self.monitors_tree.heading("target", text="Target")
        self.monitors_tree.heading("group", text="Group")
        self.monitors_tree.heading("status", text="Status")
        self.monitors_tree.heading("uptime_24h", text="Uptime 24h")
        self.monitors_tree.heading("last_check", text="Last Check")
        self.monitors_tree.heading("response_ms", text="Response (ms)")

        self.monitors_tree.column("id", width=0, stretch=False, minwidth=0)
        self.monitors_tree.column("name", width=140)
        self.monitors_tree.column("type", width=60)
        self.monitors_tree.column("target", width=200)
        self.monitors_tree.column("group", width=80)
        self.monitors_tree.column("status", width=65)
        self.monitors_tree.column("uptime_24h", width=75)
        self.monitors_tree.column("last_check", width=90)
        self.monitors_tree.column("response_ms", width=85)

        # Style the treeview
        style = ttk.Style()
        style.configure("Treeview",
                         background=COLORS["bg_card"],
                         foreground=COLORS["fg"],
                         fieldbackground=COLORS["bg_card"],
                         rowheight=28,
                         font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                         background=COLORS["bg_mid"],
                         foreground=COLORS["fg"],
                         font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", COLORS["accent"])])

        self.monitors_tree.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # Double-click to edit
        self.monitors_tree.bind("<Double-1>", lambda e: self._edit_selected_monitor())

        btn_row = ttk.Frame(tab, style="Dark.TFrame")
        btn_row.pack(fill="x", padx=15, pady=(0, 10))
        ttk.Button(btn_row, text="\U0001f504 Refresh",
                   style="Accent.TButton", command=self._refresh_monitors).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="\u2795 Add Monitor",
                   style="Accent.TButton", command=self._add_monitor_dialog).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="\u270f\ufe0f Edit",
                   style="Link.TButton", command=self._edit_selected_monitor).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="\U0001f5d1\ufe0f Delete",
                   style="Stop.TButton", command=self._delete_selected_monitor).pack(side="left")
        ttk.Button(btn_row, text="\U0001f6a8 Incidents",
                   style="Link.TButton",
                   command=self._open_incidents).pack(side="right")

    def _build_console_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text=" \U0001f4dd Console ")

        self.console = scrolledtext.ScrolledText(
            tab, wrap="word", height=25,
            bg=COLORS["bg_card"], fg=COLORS["green"],
            insertbackground=COLORS["fg"],
            selectbackground=COLORS["accent"],
            font=("Consolas", 9),
            borderwidth=0, highlightthickness=0,
        )
        self.console.pack(fill="both", expand=True, padx=15, pady=10)
        self.console.configure(state="disabled")

    def _build_settings_tab(self):
        tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(tab, text=" \u2699\ufe0f Settings ")

        # ── Scrollable container so all settings are reachable ──
        canvas = tk.Canvas(tab, bg=COLORS["bg_dark"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas, style="Dark.TFrame")

        scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Bind canvas width to tab width so cards stretch
        def _on_canvas_resize(event):
            canvas.itemconfig(canvas.find_all()[0], width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # All settings content goes inside scroll_frame (replaces 'tab')
        settings_card = ttk.Frame(scroll_frame, style="Card.TFrame")
        settings_card.pack(fill="x", padx=15, pady=10)

        ttk.Label(settings_card, text="\u2699\ufe0f Configuration",
                  style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 10))

        fields = [
            ("Server IP:", "0.0.0.0"),
            ("API Port:", "8000"),
            ("Status Page Port:", "8001"),
            ("Probe Concurrency:", "5"),
            ("Probe Interval (sec):", "60"),
            ("Alert Threshold:", "3"),
        ]

        self.settings_vars = {}
        for label_text, default in fields:
            row = ttk.Frame(settings_card, style="Card.TFrame")
            row.pack(fill="x", padx=15, pady=2)
            ttk.Label(row, text=label_text, style="Card.TLabel", width=22).pack(side="left")
            var = tk.StringVar(value=default)
            entry = tk.Entry(row, textvariable=var, width=20,
                             bg=COLORS["bg_input"], fg=COLORS["fg"],
                             insertbackground=COLORS["fg"],
                             font=("Segoe UI", 10), relief="flat")
            entry.pack(side="left", padx=(5, 0))
            self.settings_vars[label_text] = var

        # DB Info
        db_frame = ttk.Frame(settings_card, style="Card.TFrame")
        db_frame.pack(fill="x", padx=15, pady=(10, 10))
        self.db_path_label = ttk.Label(db_frame, text="\U0001f4be Database: (not initialized)",
                                        style="CardDim.TLabel")
        self.db_path_label.pack(anchor="w")

        # ── Notification Settings ────────────────────────────────────────
        notif_card = ttk.Frame(scroll_frame, style="Card.TFrame")
        notif_card.pack(fill="x", padx=15, pady=(5, 10))

        ttk.Label(notif_card, text="\U0001f514 Alert Notifications",
                  style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        ttk.Label(notif_card, text="Get notified by email, text, or desktop alert when a monitor goes down.",
                  style="CardDim.TLabel").pack(anchor="w", padx=15, pady=(0, 8))

        self.alert_vars = {}

        # Checkboxes row
        chk_row = ttk.Frame(notif_card, style="Card.TFrame")
        chk_row.pack(fill="x", padx=15, pady=2)

        self.alert_vars["toast_enabled"] = tk.BooleanVar(value=True)
        tk.Checkbutton(chk_row, text="\U0001f514 Desktop Alerts", variable=self.alert_vars["toast_enabled"],
                       bg=COLORS["bg_card"], fg=COLORS["fg"], selectcolor=COLORS["bg_input"],
                       activebackground=COLORS["bg_card"], activeforeground=COLORS["fg"],
                       font=("Segoe UI", 10)).pack(side="left", padx=(0, 15))

        self.alert_vars["email_enabled"] = tk.BooleanVar(value=False)
        tk.Checkbutton(chk_row, text="\U0001f4e7 Email", variable=self.alert_vars["email_enabled"],
                       bg=COLORS["bg_card"], fg=COLORS["fg"], selectcolor=COLORS["bg_input"],
                       activebackground=COLORS["bg_card"], activeforeground=COLORS["fg"],
                       font=("Segoe UI", 10)).pack(side="left", padx=(0, 15))

        self.alert_vars["sms_enabled"] = tk.BooleanVar(value=False)
        tk.Checkbutton(chk_row, text="\U0001f4f1 SMS Text", variable=self.alert_vars["sms_enabled"],
                       bg=COLORS["bg_card"], fg=COLORS["fg"], selectcolor=COLORS["bg_input"],
                       activebackground=COLORS["bg_card"], activeforeground=COLORS["fg"],
                       font=("Segoe UI", 10)).pack(side="left", padx=(0, 15))

        self.alert_vars["webhook_enabled"] = tk.BooleanVar(value=False)
        tk.Checkbutton(chk_row, text="\U0001f517 Webhook", variable=self.alert_vars["webhook_enabled"],
                       bg=COLORS["bg_card"], fg=COLORS["fg"], selectcolor=COLORS["bg_input"],
                       activebackground=COLORS["bg_card"], activeforeground=COLORS["fg"],
                       font=("Segoe UI", 10)).pack(side="left")

        # Email / SMTP fields
        email_fields = [
            ("SMTP Server:", "smtp_server", "smtp.gmail.com"),
            ("SMTP Port:", "smtp_port", "587"),
            ("SMTP User (email):", "smtp_user", ""),
            ("SMTP Password:", "smtp_password", ""),
            ("Send Alerts To:", "email_to", ""),
        ]

        for label_text, key, default in email_fields:
            row = ttk.Frame(notif_card, style="Card.TFrame")
            row.pack(fill="x", padx=15, pady=2)
            ttk.Label(row, text=label_text, style="Card.TLabel", width=22).pack(side="left")
            var = tk.StringVar(value=default)
            show_char = "*" if "password" in key.lower() else ""
            entry = tk.Entry(row, textvariable=var, width=30,
                             bg=COLORS["bg_input"], fg=COLORS["fg"],
                             insertbackground=COLORS["fg"], show=show_char,
                             font=("Segoe UI", 10), relief="flat")
            entry.pack(side="left", padx=(5, 0))
            self.alert_vars[key] = var

        # SMS fields
        sms_row = ttk.Frame(notif_card, style="Card.TFrame")
        sms_row.pack(fill="x", padx=15, pady=2)
        ttk.Label(sms_row, text="SMS Phone #:", style="Card.TLabel", width=22).pack(side="left")
        self.alert_vars["sms_phone"] = tk.StringVar(value="")
        tk.Entry(sms_row, textvariable=self.alert_vars["sms_phone"], width=16,
                 bg=COLORS["bg_input"], fg=COLORS["fg"], insertbackground=COLORS["fg"],
                 font=("Segoe UI", 10), relief="flat").pack(side="left", padx=(5, 0))

        ttk.Label(sms_row, text="  Carrier:", style="Card.TLabel").pack(side="left", padx=(10, 0))
        self.alert_vars["sms_carrier"] = tk.StringVar(value="xfinity")
        carrier_combo = ttk.Combobox(sms_row, textvariable=self.alert_vars["sms_carrier"], width=12,
                                      state="readonly",
                                      values=["xfinity", "verizon", "att", "tmobile", "sprint",
                                              "metro", "cricket", "boost", "google_fi", "mint", "visible"])
        carrier_combo.pack(side="left", padx=(5, 0))

        # Webhook URL
        wh_row = ttk.Frame(notif_card, style="Card.TFrame")
        wh_row.pack(fill="x", padx=15, pady=2)
        ttk.Label(wh_row, text="Webhook URL:", style="Card.TLabel", width=22).pack(side="left")
        self.alert_vars["webhook_url"] = tk.StringVar(value="")
        tk.Entry(wh_row, textvariable=self.alert_vars["webhook_url"], width=40,
                 bg=COLORS["bg_input"], fg=COLORS["fg"], insertbackground=COLORS["fg"],
                 font=("Segoe UI", 10), relief="flat").pack(side="left", padx=(5, 0))

        # Save + Test buttons
        btn_row = ttk.Frame(notif_card, style="Card.TFrame")
        btn_row.pack(fill="x", padx=15, pady=(8, 12))
        ttk.Button(btn_row, text="\U0001f4be Save Alert Settings",
                   style="Accent.TButton", command=self._save_alert_settings).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="\U0001f514 Send Test Alert",
                   style="Link.TButton", command=self._send_test_alert).pack(side="left")

        # ── Branding / White Label ──────────────────────────────────────
        brand_card = ttk.Frame(scroll_frame, style="Card.TFrame")
        brand_card.pack(fill="x", padx=15, pady=(5, 10))

        ttk.Label(brand_card, text="\U0001f3a8 Branding / White Label",
                  style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        ttk.Label(brand_card, text="Customize how the status pages look. Your name goes on it, ours stays in the footer.",
                  style="CardDim.TLabel").pack(anchor="w", padx=15, pady=(0, 8))

        self.branding_vars = {}
        brand_fields = [
            ("App Name:", "app_name", "Tech Sentinel Monitor"),
            ("Company Name:", "company_name", ""),
            ("Accent Color:", "accent_color", "#3b82f6"),
            ("Logo URL:", "logo_url", ""),
            ("Favicon URL:", "favicon_url", ""),
            ("Custom Footer:", "custom_footer", ""),
        ]

        for label_text, key, default in brand_fields:
            row = ttk.Frame(brand_card, style="Card.TFrame")
            row.pack(fill="x", padx=15, pady=2)
            ttk.Label(row, text=label_text, style="Card.TLabel", width=22).pack(side="left")
            var = tk.StringVar(value=default)
            entry = tk.Entry(row, textvariable=var, width=35,
                             bg=COLORS["bg_input"], fg=COLORS["fg"],
                             insertbackground=COLORS["fg"],
                             font=("Segoe UI", 10), relief="flat")
            entry.pack(side="left", padx=(5, 0))
            self.branding_vars[key] = var

        brand_btn_row = ttk.Frame(brand_card, style="Card.TFrame")
        brand_btn_row.pack(fill="x", padx=15, pady=(8, 12))
        ttk.Button(brand_btn_row, text="\U0001f4be Save Branding",
                   style="Accent.TButton", command=self._save_branding_settings).pack(side="left")

        # ── Version Control / Backups ───────────────────────────────────
        vc_card = ttk.Frame(scroll_frame, style="Card.TFrame")
        vc_card.pack(fill="x", padx=15, pady=(5, 10))

        ttk.Label(vc_card, text="\U0001f4be Version Control / Backups",
                  style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        ttk.Label(vc_card, text="Create backups of your database and configs. Restore to any previous version.",
                  style="CardDim.TLabel").pack(anchor="w", padx=15, pady=(0, 8))

        self.backup_label_var = tk.StringVar(value="")
        bl_row = ttk.Frame(vc_card, style="Card.TFrame")
        bl_row.pack(fill="x", padx=15, pady=2)
        ttk.Label(bl_row, text="Backup Label:", style="Card.TLabel", width=22).pack(side="left")
        tk.Entry(bl_row, textvariable=self.backup_label_var, width=30,
                 bg=COLORS["bg_input"], fg=COLORS["fg"],
                 insertbackground=COLORS["fg"],
                 font=("Segoe UI", 10), relief="flat").pack(side="left", padx=(5, 0))

        vc_btn_row = ttk.Frame(vc_card, style="Card.TFrame")
        vc_btn_row.pack(fill="x", padx=15, pady=(8, 5))
        ttk.Button(vc_btn_row, text="\U0001f4be Create Backup",
                   style="Accent.TButton", command=self._create_backup).pack(side="left", padx=(0, 10))
        ttk.Button(vc_btn_row, text="\U0001f4cb View Backups",
                   style="Link.TButton", command=self._show_backups).pack(side="left", padx=(0, 10))
        ttk.Button(vc_btn_row, text="\u267b\ufe0f Cleanup Old",
                   style="Link.TButton", command=self._cleanup_backups).pack(side="left")

        self.backup_status_label = ttk.Label(vc_card, text="", style="CardDim.TLabel")
        self.backup_status_label.pack(anchor="w", padx=15, pady=(2, 12))

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, style="Mid.TFrame")
        bar.pack(fill="x", side="bottom")

        self.statusbar_label = ttk.Label(bar, text="\u25cf Stopped — Ready to start",
                                          style="Status.TLabel")
        self.statusbar_label.pack(side="left", padx=10, pady=4)

        ttk.Label(bar, text="Tech Sentinel Monitor v1.2.0 — REGTeches",
                  style="Status.TLabel").pack(side="right", padx=10, pady=4)

    # ── URL Helpers ───────────────────────────────────────────────────────

    def _get_browse_ip(self):
        """Get the IP/hostname for browser URLs. Uses Server IP setting,
        but substitutes localhost if set to 0.0.0.0 (bind-all)."""
        ip = self.settings_vars.get("Server IP:", tk.StringVar(value="0.0.0.0")).get().strip()
        if not ip or ip == "0.0.0.0":
            import socket
            try:
                # Get local IP by connecting to a known address
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
            except Exception:
                ip = "localhost"
        return ip

    def _open_api(self):
        port = self.settings_vars.get("API Port:", tk.StringVar(value="8000")).get()
        webbrowser.open(f"http://{self._get_browse_ip()}:{port}")

    def _open_docs(self):
        port = self.settings_vars.get("API Port:", tk.StringVar(value="8000")).get()
        webbrowser.open(f"http://{self._get_browse_ip()}:{port}/docs")

    def _open_status(self):
        port = self.settings_vars.get("Status Page Port:", tk.StringVar(value="8001")).get()
        webbrowser.open(f"http://{self._get_browse_ip()}:{port}")

    def _open_incidents(self):
        port = self.settings_vars.get("Status Page Port:", tk.StringVar(value="8001")).get()
        webbrowser.open(f"http://{self._get_browse_ip()}:{port}/incidents")

    # ── Service Control ──────────────────────────────────────────────────────

    def _start_services(self):
        if self.api_running:
            return

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.statusbar_label.configure(text="\u25cf Starting services...")

        # Start in background thread
        threading.Thread(target=self._do_start, daemon=True).start()

    def _do_start(self):
        try:
            # 1. Initialize database
            logger.info("Initializing SQLite database...")
            from windows.local_database import init_db
            self.db_path = init_db()
            logger.info("Database ready: %s", self.db_path)
            self.root.after(0, lambda: self.db_path_label.configure(
                text=f"\U0001f4be Database: {self.db_path}"))

            # 2. Initialize alert engine
            logger.info("Initializing alert engine...")
            from windows.local_alert_engine import init_alert_config
            config_dir = os.path.dirname(self.db_path)
            self.alert_config = init_alert_config(config_dir)
            self._load_alert_settings_to_ui()

            # 2b. Initialize branding config
            logger.info("Initializing branding config...")
            from windows.local_branding import init_branding_config
            init_branding_config(config_dir)
            self._load_branding_settings_to_ui()

            # 2c. Auto-backup on start
            try:
                from windows.local_version_control import VersionManager
                vm = VersionManager(config_dir)
                vm.create_backup(label="auto-start", auto=True)
                vm.cleanup_old_backups(keep=20)
                logger.info("Auto-backup created on startup")
            except Exception as e:
                logger.warning("Auto-backup failed: %s", e)

            # 3. Start API server
            logger.info("Starting Control Plane API on port 8000...")
            api_port = int(self.settings_vars.get("API Port:", tk.StringVar(value="8000")).get())
            self._start_api(api_port)

            # 4. Start Status Page server
            logger.info("Starting Status Page on port 8001...")
            status_port = int(self.settings_vars.get("Status Page Port:", tk.StringVar(value="8001")).get())
            self._start_status_page(status_port)

            # 5. Start Probe Worker (with alert callback)
            logger.info("Starting Probe Worker...")
            concurrency = int(self.settings_vars.get("Probe Concurrency:", tk.StringVar(value="5")).get())
            self._start_worker(concurrency)

            self.api_running = True
            self.worker_running = True

            # Update UI
            self.root.after(0, self._update_ui_running)
            logger.info("\u2705 All services started successfully!")

        except Exception as e:
            logger.error("Failed to start services: %s", e)
            self.root.after(0, lambda: messagebox.showerror("Startup Error", str(e)))
            self.root.after(0, lambda: self.start_btn.configure(state="normal"))

    def _start_api(self, port: int):
        import uvicorn
        from windows.local_api import create_app

        app = create_app()
        config = uvicorn.Config(app, host="0.0.0.0", port=port,
                                log_level="warning", log_config=None)
        self.uvicorn_server = uvicorn.Server(config)

        thread = threading.Thread(target=self.uvicorn_server.run, daemon=True, name="api-server")
        thread.start()
        self.api_thread = thread

        # Wait for it to be ready
        time.sleep(2)

    def _start_status_page(self, port: int):
        import uvicorn

        # Create a minimal status page app for local mode
        from windows.local_status_page import create_status_app
        app = create_status_app()

        config = uvicorn.Config(app, host="0.0.0.0", port=port,
                                log_level="warning", log_config=None)
        self.status_server = uvicorn.Server(config)

        thread = threading.Thread(target=self.status_server.run, daemon=True, name="status-server")
        thread.start()
        time.sleep(1)

    def _start_worker(self, concurrency: int):
        from windows.local_probe_worker import LocalProbeWorker
        from windows.local_alert_engine import evaluate_probe_result
        self.worker_instance = LocalProbeWorker(
            concurrency=concurrency,
            on_result=evaluate_probe_result,
        )
        self.worker_instance.start()

    def _stop_services(self):
        if not self.api_running:
            return

        self.stop_btn.configure(state="disabled")
        self.statusbar_label.configure(text="\u25cf Stopping services...")

        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self):
        try:
            if self.worker_instance:
                logger.info("Stopping probe worker...")
                self.worker_instance.stop()
                self.worker_instance = None

            if self.uvicorn_server:
                logger.info("Stopping API server...")
                self.uvicorn_server.should_exit = True
                self.uvicorn_server = None

            if self.status_server:
                logger.info("Stopping status page...")
                self.status_server.should_exit = True
                self.status_server = None

            self.api_running = False
            self.worker_running = False
            logger.info("\u23f9 All services stopped")

            self.root.after(0, self._update_ui_stopped)

        except Exception as e:
            logger.error("Error stopping services: %s", e)

    def _update_ui_running(self):
        self.api_card._status_label.configure(text="\u25cf Running", foreground=COLORS["green"])
        self.worker_card._status_label.configure(text="\u25cf Running", foreground=COLORS["green"])
        self.status_card._status_label.configure(text="\u25cf Running", foreground=COLORS["green"])
        self.statusbar_label.configure(text="\u25cf All services running")

    def _update_ui_stopped(self):
        self.api_card._status_label.configure(text="\u25cf Stopped", foreground=COLORS["red"])
        self.worker_card._status_label.configure(text="\u25cf Stopped", foreground=COLORS["red"])
        self.status_card._status_label.configure(text="\u25cf Stopped", foreground=COLORS["red"])
        self.statusbar_label.configure(text="\u25cf Stopped — Ready to start")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    # ── NOC Import ────────────────────────────────────────────────────────────

    def _import_noc_config(self):
        """Open file dialog to select a noc_config.json and import all nodes."""
        if not self.api_running:
            messagebox.showwarning("Not Running", "Start services first, then import your NOC config.")
            return

        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="Select NOC Config JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir="C:\\code\\NOC_Dashboard",
        )
        if not file_path:
            return

        self.import_status.configure(text="\u23f3 Importing...", foreground=COLORS["yellow"])
        threading.Thread(target=self._do_noc_import, args=(file_path,), daemon=True).start()

    def _do_noc_import(self, config_path: str):
        try:
            from windows.noc_importer import import_noc_config
            result = import_noc_config(config_path)

            if "error" in result:
                self.root.after(0, lambda: self.import_status.configure(
                    text=f"\u274c {result['error']}", foreground=COLORS["red"]))
                return

            count = result["monitors_created"]
            url = result["status_page_url"]
            logger.info("NOC import: %d monitors created from %s", count, config_path)
            logger.info("Status page: %s", url)

            def _update():
                self.import_status.configure(
                    text=f"\u2705 {count} monitors imported!",
                    foreground=COLORS["green"])
                self._refresh_monitors()
                if messagebox.askyesno("Import Complete",
                    f"{count} monitors imported from your NOC config!\n\n"
                    f"Open the status page in your browser?\n{url}"):
                    webbrowser.open(url)

            self.root.after(0, _update)

        except Exception as e:
            logger.error("NOC import failed: %s", e)
            self.root.after(0, lambda: self.import_status.configure(
                text=f"\u274c Import failed: {e}", foreground=COLORS["red"]))

    def _import_demo_layout(self):
        """Import the built-in ACME Corp demo layout."""
        if not self.api_running:
            messagebox.showwarning("Not Running", "Start services first, then load the demo.")
            return

        # Find the demo layout file
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        demo_file = os.path.join(app_dir, "demo", "example-network-layout.json")

        if not os.path.exists(demo_file):
            # Try ACME demo instead
            demo_file = os.path.join(app_dir, "demo", "ts-uptimerobot-layout.json")

        if not os.path.exists(demo_file):
            messagebox.showerror("Not Found", "Demo layout file not found in demo/ folder.")
            return

        self.import_status.configure(text="\u23f3 Loading demo...", foreground=COLORS["yellow"])
        threading.Thread(target=self._do_demo_import, args=(demo_file,), daemon=True).start()

    def _do_demo_import(self, layout_path: str):
        try:
            import json
            from windows.local_database import (
                create_tenant, create_monitor, create_alert_channel,
                create_status_page,
            )
            from windows.local_queue import enqueue_job

            with open(layout_path, "r", encoding="utf-8") as f:
                layout = json.load(f)

            tenant_cfg = layout["tenant"]
            tenant = create_tenant(name=tenant_cfg["name"], slug=tenant_cfg["slug"])
            tenant_id = tenant["id"]

            monitor_ids = {}
            for m in layout.get("monitors", []):
                result = create_monitor(
                    tenant_id=tenant_id, name=m["name"],
                    monitor_type=m["monitor_type"], target=m["target"],
                    interval_seconds=m.get("interval_seconds", 60),
                    timeout_seconds=m.get("timeout_seconds", 10),
                    external_id=m.get("external_id"),
                    config=m.get("config"),
                )
                monitor_ids[m.get("external_id", m["name"])] = result["id"]
                enqueue_job({
                    "monitor_id": result["id"],
                    "tenant_id": result["tenant_id"],
                    "monitor_type": result["monitor_type"],
                    "target": result["target"],
                    "interval_seconds": str(result["interval_seconds"]),
                    "timeout_seconds": str(result["timeout_seconds"]),
                    "config": result.get("config", "{}"),
                })

            for c in layout.get("alert_channels", []):
                create_alert_channel(
                    tenant_id=tenant_id, name=c["name"],
                    channel_type=c["channel_type"],
                    config=c.get("config", {}),
                    external_id=c.get("external_id"),
                )

            for sp in layout.get("status_pages", []):
                resolved = [monitor_ids[ref] for ref in sp.get("monitor_refs", []) if ref in monitor_ids]
                create_status_page(
                    tenant_id=tenant_id, name=sp["name"], slug=sp["slug"],
                    theme=sp.get("theme"), monitor_ids=resolved or sp.get("monitor_ids", []),
                    external_id=sp.get("external_id"),
                )

            count = len(monitor_ids)
            slug = layout.get("status_pages", [{}])[0].get("slug", "status")
            sp_port = self.settings_vars.get("Status Page Port:", tk.StringVar(value="8001")).get()
            url = f"http://{self._get_browse_ip()}:{sp_port}/status/{slug}"

            logger.info("Demo import: %d monitors from %s", count, layout_path)

            def _update():
                self.import_status.configure(
                    text=f"\u2705 {count} monitors loaded!",
                    foreground=COLORS["green"])
                self._refresh_monitors()
                if messagebox.askyesno("Demo Loaded",
                    f"{count} monitors provisioned!\n\nOpen status page?\n{url}"):
                    webbrowser.open(url)

            self.root.after(0, _update)

        except Exception as e:
            logger.error("Demo import failed: %s", e)
            self.root.after(0, lambda: self.import_status.configure(
                text=f"\u274c Failed: {e}", foreground=COLORS["red"]))

    # ── Refresh Loops ────────────────────────────────────────────────────────

    def _refresh_logs(self):
        with LOG_LOCK:
            if LOG_BUFFER:
                self.console.configure(state="normal")
                for line in LOG_BUFFER:
                    self.console.insert("end", line + "\n")
                LOG_BUFFER.clear()
                self.console.see("end")
                self.console.configure(state="disabled")
        self.root.after(500, self._refresh_logs)

    def _refresh_stats(self):
        if self.worker_instance:
            self.stat_checks._value_label.configure(text=str(self.worker_instance.total_checks))
            self.stat_up._value_label.configure(text=str(self.worker_instance.checks_up))
            self.stat_down._value_label.configure(text=str(self.worker_instance.checks_down))

            from windows.local_queue import get_queue_size
            self.stat_queue._value_label.configure(text=str(get_queue_size()))

            from windows.local_database import get_db_size_mb
            self.stat_db._value_label.configure(text=f"{get_db_size_mb():.1f} MB")

        self.root.after(2000, self._refresh_stats)

    def _refresh_monitors(self):
        if not self.api_running:
            return

        # Clear existing
        for item in self.monitors_tree.get_children():
            self.monitors_tree.delete(item)

        try:
            from windows.local_database import list_tenants, list_monitors, get_recent_results, get_uptime_percent

            tenants = list_tenants()
            for tenant in tenants:
                monitors = list_monitors(tenant["id"])
                for m in monitors:
                    results = get_recent_results(m["id"], limit=1)
                    if results:
                        last = results[0]
                        status = last["status"]
                        resp = f"{last.get('response_time_ms', 0):.0f}" if last.get("response_time_ms") else "-"
                        checked = last.get("checked_at", "-")
                        if isinstance(checked, str) and len(checked) > 19:
                            checked = checked[11:19]
                    else:
                        status = "pending"
                        resp = "-"
                        checked = "-"

                    # Uptime percentage
                    try:
                        uptime = f"{get_uptime_percent(m['id'], 24):.1f}%"
                    except Exception:
                        uptime = "-"

                    group = m.get("group_name", "") or "-"
                    tag = "up" if status == "up" else "down" if status in ("down", "timeout") else "pending"
                    self.monitors_tree.insert("", "end", values=(
                        m["id"], m["name"], m["monitor_type"], m["target"],
                        group, status, uptime, checked, resp,
                    ), tags=(tag,))

            self.monitors_tree.tag_configure("up", foreground=COLORS["green"])
            self.monitors_tree.tag_configure("down", foreground=COLORS["red"])
            self.monitors_tree.tag_configure("pending", foreground=COLORS["yellow"])

        except Exception as e:
            logger.error("Failed to refresh monitors: %s", e)

    # ── Monitor Add / Edit / Delete Dialogs ─────────────────────────────────

    def _get_selected_monitor_id(self):
        """Get the monitor ID from the selected treeview row."""
        sel = self.monitors_tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Select a monitor first.")
            return None
        values = self.monitors_tree.item(sel[0], "values")
        return values[0] if values else None

    def _add_monitor_dialog(self):
        """Open dialog to add a new monitor."""
        if not self.api_running:
            messagebox.showwarning("Not Running", "Start services first.")
            return
        self._open_monitor_dialog(mode="add")

    def _edit_selected_monitor(self):
        """Open dialog to edit the selected monitor."""
        if not self.api_running:
            return
        monitor_id = self._get_selected_monitor_id()
        if not monitor_id:
            return
        self._open_monitor_dialog(mode="edit", monitor_id=monitor_id)

    def _delete_selected_monitor(self):
        """Delete the selected monitor after confirmation."""
        if not self.api_running:
            return
        monitor_id = self._get_selected_monitor_id()
        if not monitor_id:
            return

        sel = self.monitors_tree.selection()
        name = self.monitors_tree.item(sel[0], "values")[1]

        if not messagebox.askyesno("Delete Monitor",
                f"Delete \"{name}\"?\n\nThis will remove the monitor and all its check history."):
            return

        try:
            from windows.local_database import delete_monitor
            delete_monitor(monitor_id)
            logger.info("Deleted monitor: %s (%s)", name, monitor_id)
            self._refresh_monitors()
        except Exception as e:
            logger.error("Failed to delete monitor: %s", e)
            messagebox.showerror("Error", f"Failed to delete monitor: {e}")

    def _open_monitor_dialog(self, mode="add", monitor_id=None):
        """Open a Toplevel dialog for adding or editing a monitor."""
        from windows.local_database import get_monitor, list_tenants

        existing = None
        if mode == "edit" and monitor_id:
            existing = get_monitor(monitor_id)
            if not existing:
                messagebox.showerror("Error", "Monitor not found.")
                return

        dlg = tk.Toplevel(self.root)
        dlg.title("\u2795 Add Monitor" if mode == "add" else f"\u270f\ufe0f Edit: {existing['name']}")
        dlg.geometry("480x500")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        # ── Form fields ─────────────────────────────────────────────────
        form = ttk.Frame(dlg, style="Card.TFrame")
        form.pack(fill="both", expand=True, padx=15, pady=15)

        fields = {}

        def add_field(label, default="", row=0, widget_type="entry"):
            ttk.Label(form, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky="w", padx=10, pady=6)
            var = tk.StringVar(value=default)
            if widget_type == "combo":
                w = ttk.Combobox(form, textvariable=var, width=30, state="readonly",
                                  values=["http", "tcp", "ping", "heartbeat"])
                w.configure(font=("Segoe UI", 10))
            else:
                w = tk.Entry(form, textvariable=var, width=32,
                              bg=COLORS["bg_input"], fg=COLORS["fg"],
                              insertbackground=COLORS["fg"],
                              font=("Segoe UI", 10), relief="flat")
            w.grid(row=row, column=1, sticky="w", padx=(0, 10), pady=6)
            fields[label] = var
            return var

        add_field("Name:", existing["name"] if existing else "", row=0)
        add_field("Type:", existing["monitor_type"] if existing else "ping", row=1, widget_type="combo")
        add_field("Target:", existing["target"] if existing else "", row=2)
        add_field("Interval (sec):", str(existing["interval_seconds"]) if existing else "60", row=3)
        add_field("Timeout (sec):", str(existing["timeout_seconds"]) if existing else "10", row=4)

        # HTTP-specific config
        ttk.Label(form, text="HTTP Method:", style="Card.TLabel").grid(
            row=5, column=0, sticky="w", padx=10, pady=6)
        method_var = tk.StringVar(value="GET")
        if existing and existing.get("config"):
            cfg = existing["config"]
            if isinstance(cfg, str):
                import json
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            method_var.set(cfg.get("method", "GET"))
        method_combo = ttk.Combobox(form, textvariable=method_var, width=30,
                                     state="readonly", values=["GET", "HEAD", "POST"])
        method_combo.configure(font=("Segoe UI", 10))
        method_combo.grid(row=5, column=1, sticky="w", padx=(0, 10), pady=6)

        add_field("Expected Status:", "200", row=6)
        if existing and existing.get("config"):
            cfg = existing["config"]
            if isinstance(cfg, str):
                import json
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            if isinstance(cfg, dict) and cfg.get("expected_status"):
                fields["Expected Status:"].set(str(cfg["expected_status"]))

        # Group name field
        add_field("Group:", existing.get("group_name", "") if existing else "", row=7)

        # ── Tenant selector (for Add mode) ──────────────────────────────
        tenant_id_for_add = None
        if mode == "add":
            tenants = list_tenants()
            if not tenants:
                messagebox.showwarning("No Tenants",
                    "No tenants exist yet. Import a NOC config or demo first to create one.")
                dlg.destroy()
                return
            tenant_names = [f"{t['name']} ({t['slug']})" for t in tenants]
            tenant_map = {f"{t['name']} ({t['slug']})": t["id"] for t in tenants}

            ttk.Label(form, text="Tenant:", style="Card.TLabel").grid(
                row=8, column=0, sticky="w", padx=10, pady=6)
            tenant_var = tk.StringVar(value=tenant_names[0])
            tenant_combo = ttk.Combobox(form, textvariable=tenant_var, width=30,
                                         state="readonly", values=tenant_names)
            tenant_combo.configure(font=("Segoe UI", 10))
            tenant_combo.grid(row=8, column=1, sticky="w", padx=(0, 10), pady=6)

        # ── Save / Cancel buttons ────────────────────────────────────────
        btn_frame = ttk.Frame(form, style="Card.TFrame")
        btn_frame.grid(row=9, column=0, columnspan=2, pady=(15, 10))

        def _save():
            name = fields["Name:"].get().strip()
            mtype = fields["Type:"].get().strip()
            target = fields["Target:"].get().strip()
            interval = fields["Interval (sec):"].get().strip()
            timeout = fields["Timeout (sec):"].get().strip()
            group = fields["Group:"].get().strip()

            if not name or not target:
                messagebox.showwarning("Missing Fields", "Name and Target are required.", parent=dlg)
                return

            try:
                interval_int = int(interval)
                timeout_int = int(timeout)
            except ValueError:
                messagebox.showwarning("Invalid", "Interval and Timeout must be numbers.", parent=dlg)
                return

            config = None
            if mtype == "http":
                config = {
                    "method": method_var.get(),
                    "expected_status": int(fields["Expected Status:"].get() or 200),
                }

            try:
                if mode == "add":
                    tid = tenant_map[tenant_var.get()]
                    from windows.local_database import create_monitor, _get_conn
                    from windows.local_queue import enqueue_job
                    m = create_monitor(
                        tenant_id=tid, name=name, monitor_type=mtype,
                        target=target, interval_seconds=interval_int,
                        timeout_seconds=timeout_int, config=config,
                    )
                    # Set group_name
                    if group:
                        conn = _get_conn()
                        conn.execute("UPDATE monitors SET group_name=? WHERE id=?", (group, m["id"]))
                        conn.commit()
                    enqueue_job({
                        "monitor_id": m["id"], "tenant_id": m["tenant_id"],
                        "monitor_type": m["monitor_type"], "target": m["target"],
                        "interval_seconds": str(m["interval_seconds"]),
                        "timeout_seconds": str(m["timeout_seconds"]),
                        "config": m.get("config", "{}"),
                    })
                    logger.info("Added monitor: %s (%s → %s)", name, mtype, target)
                else:
                    from windows.local_database import _get_conn
                    import json as _json
                    conn = _get_conn()
                    conn.execute(
                        """UPDATE monitors SET name=?, monitor_type=?, target=?,
                           interval_seconds=?, timeout_seconds=?, config=?,
                           group_name=?, updated_at=datetime('now')
                           WHERE id=?""",
                        (name, mtype, target, interval_int, timeout_int,
                         _json.dumps(config) if config else None, group, monitor_id),
                    )
                    conn.commit()
                    logger.info("Updated monitor: %s (%s)", name, monitor_id)

                dlg.destroy()
                self._refresh_monitors()

            except Exception as e:
                logger.error("Failed to save monitor: %s", e)
                messagebox.showerror("Error", f"Failed to save: {e}", parent=dlg)

        ttk.Button(btn_frame, text="\U0001f4be Save", style="Accent.TButton",
                   command=_save).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="\u274c Cancel", style="Link.TButton",
                   command=dlg.destroy).pack(side="left")

    # ── Alert Settings ──────────────────────────────────────────────────────

    def _save_alert_settings(self):
        """Save notification settings from UI to config file."""
        try:
            from windows.local_alert_engine import get_alert_config, save_alert_config
            cfg = get_alert_config()

            cfg.toast_enabled = self.alert_vars["toast_enabled"].get()
            cfg.email_enabled = self.alert_vars["email_enabled"].get()
            cfg.sms_enabled = self.alert_vars["sms_enabled"].get()
            cfg.webhook_enabled = self.alert_vars["webhook_enabled"].get()

            cfg.smtp_server = self.alert_vars["smtp_server"].get()
            cfg.smtp_port = int(self.alert_vars["smtp_port"].get() or 587)
            cfg.smtp_user = self.alert_vars["smtp_user"].get()
            cfg.smtp_password = self.alert_vars["smtp_password"].get()
            cfg.email_to = self.alert_vars["email_to"].get()

            cfg.sms_phone = self.alert_vars["sms_phone"].get()
            cfg.sms_carrier = self.alert_vars["sms_carrier"].get()

            cfg.webhook_url = self.alert_vars["webhook_url"].get()

            cfg.threshold = int(self.settings_vars.get("Alert Threshold:", tk.StringVar(value="3")).get())

            save_alert_config()
            logger.info("\u2705 Alert settings saved")
            messagebox.showinfo("Saved", "Alert notification settings saved!")
        except Exception as e:
            logger.error("Failed to save alert settings: %s", e)
            messagebox.showerror("Error", f"Failed to save: {e}")

    def _load_alert_settings_to_ui(self):
        """Load alert config values into the UI fields (called from main thread via .after)."""
        def _do_load():
            try:
                from windows.local_alert_engine import get_alert_config
                cfg = get_alert_config()

                self.alert_vars["toast_enabled"].set(cfg.toast_enabled)
                self.alert_vars["email_enabled"].set(cfg.email_enabled)
                self.alert_vars["sms_enabled"].set(cfg.sms_enabled)
                self.alert_vars["webhook_enabled"].set(cfg.webhook_enabled)

                self.alert_vars["smtp_server"].set(cfg.smtp_server)
                self.alert_vars["smtp_port"].set(str(cfg.smtp_port))
                self.alert_vars["smtp_user"].set(cfg.smtp_user)
                self.alert_vars["smtp_password"].set(cfg.smtp_password)
                self.alert_vars["email_to"].set(cfg.email_to)

                self.alert_vars["sms_phone"].set(cfg.sms_phone)
                self.alert_vars["sms_carrier"].set(cfg.sms_carrier)

                self.alert_vars["webhook_url"].set(cfg.webhook_url)

                self.settings_vars["Alert Threshold:"].set(str(cfg.threshold))
            except Exception as e:
                logger.error("Failed to load alert settings to UI: %s", e)

        self.root.after(0, _do_load)

    def _send_test_alert(self):
        """Send a test alert through all enabled channels."""
        self._save_alert_settings()
        threading.Thread(target=self._do_test_alert, daemon=True).start()

    def _do_test_alert(self):
        try:
            from windows.local_alert_engine import send_test_alert
            results = send_test_alert()

            lines = []
            all_ok = True
            for channel, status in results.items():
                if status == "ok":
                    lines.append(f"\u2705 {channel} — Sent!")
                elif status == "disabled":
                    lines.append(f"\u23ed\ufe0f {channel} — Disabled")
                else:
                    lines.append(f"\u274c {channel} — {status}")
                    all_ok = False

            summary = "\n".join(lines)

            def _show():
                if all_ok:
                    messagebox.showinfo("Test Alert Results", summary)
                else:
                    messagebox.showwarning("Test Alert Results", summary)

            self.root.after(0, _show)
        except Exception as e:
            logger.error("Test alert failed: %s", e)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Test alert failed: {e}"))

    # ── Branding Settings ──────────────────────────────────────────────────

    def _save_branding_settings(self):
        """Save branding/white-label settings."""
        try:
            from windows.local_branding import get_branding_config, save_branding_config
            cfg = get_branding_config()
            for key, var in self.branding_vars.items():
                setattr(cfg, key, var.get())
            save_branding_config()
            logger.info("\u2705 Branding settings saved")
            messagebox.showinfo("Saved", "Branding settings saved! Refresh the status page to see changes.")
        except Exception as e:
            logger.error("Failed to save branding: %s", e)
            messagebox.showerror("Error", f"Failed to save branding: {e}")

    def _load_branding_settings_to_ui(self):
        """Load branding config into UI fields."""
        def _do():
            try:
                from windows.local_branding import get_branding_config
                cfg = get_branding_config()
                for key, var in self.branding_vars.items():
                    val = getattr(cfg, key, "")
                    var.set(val if val else "")
            except Exception as e:
                logger.error("Failed to load branding to UI: %s", e)
        self.root.after(0, _do)

    # ── Version Control / Backups ────────────────────────────────────────────

    def _get_version_manager(self):
        from windows.local_version_control import VersionManager
        app_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor"
        )
        return VersionManager(app_dir)

    def _create_backup(self):
        """Create a manual backup."""
        try:
            vm = self._get_version_manager()
            label = self.backup_label_var.get().strip() or "manual"
            rec = vm.create_backup(label=label)
            logger.info("Backup created: %s (%.2f MB)", rec["id"], rec["total_size_mb"])
            self.backup_status_label.configure(
                text=f"\u2705 Backup created: {rec['id']} ({rec['total_size_mb']} MB, {len(rec['files'])} files)"
            )
            messagebox.showinfo("Backup Created",
                f"Backup: {rec['id']}\n"
                f"Files: {len(rec['files'])}\n"
                f"Size: {rec['total_size_mb']} MB\n"
                f"Location: {rec['path']}")
        except Exception as e:
            logger.error("Backup failed: %s", e)
            messagebox.showerror("Error", f"Backup failed: {e}")

    def _show_backups(self):
        """Show a dialog listing all backups with restore/delete options."""
        try:
            vm = self._get_version_manager()
            backups = vm.list_backups()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to list backups: {e}")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("\U0001f4be Backup History")
        dlg.geometry("700x450")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=f"\U0001f4be {len(backups)} Backups Available",
                  style="Dark.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        # Treeview
        cols = ("id", "timestamp", "label", "files", "size_mb", "version")
        tree = ttk.Treeview(dlg, columns=cols, show="headings", height=12)
        tree.heading("id", text="Backup ID")
        tree.heading("timestamp", text="Date/Time")
        tree.heading("label", text="Label")
        tree.heading("files", text="Files")
        tree.heading("size_mb", text="Size (MB)")
        tree.heading("version", text="App Version")
        tree.column("id", width=200)
        tree.column("timestamp", width=130)
        tree.column("label", width=100)
        tree.column("files", width=50)
        tree.column("size_mb", width=70)
        tree.column("version", width=80)

        for b in backups:
            ts = b.get("timestamp", "")[:19].replace("T", " ")
            tree.insert("", "end", values=(
                b["id"], ts, b.get("label", ""),
                len(b.get("files", [])), b.get("total_size_mb", 0),
                b.get("app_version", "?"),
            ))

        tree.pack(fill="both", expand=True, padx=15, pady=5)

        btn_row = ttk.Frame(dlg, style="Dark.TFrame")
        btn_row.pack(fill="x", padx=15, pady=(5, 15))

        def _restore():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Select", "Select a backup to restore.", parent=dlg)
                return
            bid = tree.item(sel[0], "values")[0]
            if not messagebox.askyesno("Restore Backup",
                    f"Restore from backup: {bid}?\n\n"
                    "This will overwrite your current database and configs.\n"
                    "A safety backup of the current state will be created first.",
                    parent=dlg):
                return
            try:
                ok = vm.restore_backup(bid)
                if ok:
                    messagebox.showinfo("Restored",
                        f"Backup {bid} restored!\n\nRestart the application for changes to take effect.",
                        parent=dlg)
                else:
                    messagebox.showerror("Error", "Restore failed — backup not found.", parent=dlg)
            except Exception as e:
                messagebox.showerror("Error", f"Restore failed: {e}", parent=dlg)

        def _delete():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Select", "Select a backup to delete.", parent=dlg)
                return
            bid = tree.item(sel[0], "values")[0]
            if messagebox.askyesno("Delete Backup", f"Delete backup: {bid}?", parent=dlg):
                vm.delete_backup(bid)
                tree.delete(sel[0])
                logger.info("Deleted backup: %s", bid)

        ttk.Button(btn_row, text="\u267b\ufe0f Restore Selected",
                   style="Accent.TButton", command=_restore).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="\U0001f5d1\ufe0f Delete Selected",
                   style="Stop.TButton", command=_delete).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="\u274c Close",
                   style="Link.TButton", command=dlg.destroy).pack(side="right")

    def _cleanup_backups(self):
        """Remove old backups, keep last 20."""
        try:
            vm = self._get_version_manager()
            vm.cleanup_old_backups(keep=20)
            self.backup_status_label.configure(text="\u2705 Old backups cleaned up (keeping last 20)")
        except Exception as e:
            messagebox.showerror("Error", f"Cleanup failed: {e}")

    # ── About & Manual Dialogs ────────────────────────────────────────────

    def _show_about(self):
        """Show the About dialog."""
        dlg = tk.Toplevel(self.root)
        dlg.title("About Tech Sentinel Monitor")
        dlg.geometry("460x500")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        card = ttk.Frame(dlg, style="Card.TFrame")
        card.pack(fill="both", expand=True, padx=20, pady=20)

        ttk.Label(card, text="\U0001f6e1\ufe0f Tech Sentinel Monitor",
                  style="Card.TLabel", font=("Segoe UI", 16, "bold")).pack(pady=(20, 5))
        from windows.local_version_control import APP_VERSION
        ttk.Label(card, text=f"Version {APP_VERSION} — Windows Standalone",
                  style="CardDim.TLabel").pack()

        ttk.Separator(card, orient="horizontal").pack(fill="x", padx=30, pady=15)

        info_text = (
            "A professional network uptime monitoring platform\n"
            "built for IT technicians and NOC operators.\n\n"
            "\U0001f4e1  HTTP / TCP / Ping / Heartbeat probes\n"
            "\U0001f4ca  Real-time status page with sparklines & uptime %\n"
            "\U0001f514  Email, SMS, Desktop & Webhook alerts\n"
            "\U0001f6a8  Incident tracking & history\n"
            "\U0001f3a8  White-label / private label branding\n"
            "\U0001f4bb  Windows & Linux system agents\n"
            "\U0001f4be  Version control & config backups\n"
            "\U0001f310  Web-based monitor management\n"
            "\U0001f4e6  Single-file EXE — portable & standalone"
        )
        ttk.Label(card, text=info_text, style="Card.TLabel",
                  justify="center", wraplength=380).pack(pady=(0, 15))

        ttk.Separator(card, orient="horizontal").pack(fill="x", padx=30, pady=5)

        ttk.Label(card, text="Developed by Ronald Goodchild",
                  style="Card.TLabel", font=("Segoe UI", 10, "bold")).pack(pady=(10, 2))
        ttk.Label(card, text="REGTeches / Bay Area Tech",
                  style="CardDim.TLabel").pack()
        ttk.Label(card, text="\u00a9 2026 REGTeches — All Rights Reserved",
                  style="CardDim.TLabel").pack(pady=(5, 15))

        ttk.Button(card, text="OK", style="Accent.TButton",
                   command=dlg.destroy).pack(pady=(0, 15))

    def _show_manual(self):
        """Show the Manual / How-To guide in a scrollable window."""
        dlg = tk.Toplevel(self.root)
        dlg.title("\u2753 Tech Sentinel Monitor — User Manual")
        dlg.geometry("700x620")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.resizable(True, True)
        dlg.transient(self.root)

        # Scrollable text widget
        from tkinter import scrolledtext
        manual = scrolledtext.ScrolledText(
            dlg, wrap="word",
            bg=COLORS["bg_card"], fg=COLORS["fg"],
            insertbackground=COLORS["fg"],
            selectbackground=COLORS["accent"],
            font=("Segoe UI", 10),
            borderwidth=0, highlightthickness=0,
            padx=20, pady=15,
        )
        manual.pack(fill="both", expand=True, padx=10, pady=10)

        manual_text = """
\U0001f6e1\ufe0f  TECH SENTINEL MONITOR — USER MANUAL
═══════════════════════════════════════════════
Version 1.0.0 | REGTeches / Ronald Goodchild


\U0001f680  QUICK START
───────────────────────────────────────────────

1. Launch the application (double-click the EXE or run: py windows\\run.py)
2. Click "\u25b6\ufe0f Start All Services" on the Dashboard tab
3. Wait for all 3 status indicators to turn green:
   • \U0001f4e1 Control Plane API (port 8000)
   • \u2699\ufe0f Probe Worker (threaded)
   • \U0001f4ca Status Page (port 8001)
4. Import your monitors (see below)
5. Open the Status Page in your browser


\U0001f4c2  IMPORTING MONITORS
───────────────────────────────────────────────

Option A — Load NOC Config:
   • Click "\U0001f4c2 Load NOC Config" on the Dashboard
   • Browse to your noc_config.json file
   • All nodes, connections, and services are auto-imported
   • A status page is created automatically

Option B — Load ACME Demo:
   • Click "\U0001f3e2 Load ACME Demo" for a sample setup
   • Great for testing and learning the system

Option C — Add Manually:
   • Go to the Monitors tab → click "\u2795 Add Monitor"
   • Or open http://localhost:8001/manage in your browser


\U0001f50d  MONITOR TYPES
───────────────────────────────────────────────

\U0001f4e1 PING    — ICMP ping to check if a host is reachable
               Target: IP address or hostname (e.g. 192.168.1.248)

\U0001f310 HTTP    — HTTP/HTTPS request to check a web service
               Target: Full URL (e.g. http://192.168.1.248:5000)
               Config: Method (GET/HEAD/POST), Expected Status Code

\U0001f50c TCP     — TCP port connection test
               Target: host:port (e.g. 192.168.1.248:445)

\U0001f493 HEARTBEAT — Passive check-in monitoring
               Target: Service name or identifier


\U0001f4ca  STATUS PAGE (Web Dashboard)
───────────────────────────────────────────────

• Open: http://localhost:8001
• Shows all status pages with clickable cards
• Cards are displayed 3-across in a responsive grid
• Click any card to navigate to that service
• Auto-refreshes every 30 seconds
• Manage link for adding/editing/deleting monitors


\U0001f310  API ENDPOINTS
───────────────────────────────────────────────

• API Root:       http://localhost:8000
• API Docs:       http://localhost:8000/docs  (Swagger UI)
• Status Pages:   http://localhost:8001
• Manage Page:    http://localhost:8001/manage


\U0001f514  ALERT NOTIFICATIONS
───────────────────────────────────────────────

Configure alerts in Settings tab → Alert Notifications section:

\U0001f514 Desktop Alerts:
   • Windows toast notifications (enabled by default)
   • No setup needed

\U0001f4e7 Email Alerts:
   1. Check the "\U0001f4e7 Email" checkbox
   2. SMTP Server: smtp.gmail.com (for Gmail)
   3. SMTP Port: 587
   4. SMTP User: your-email@gmail.com
   5. SMTP Password: Use a Gmail App Password!
      → Go to https://myaccount.google.com/apppasswords
      → Generate an app password for "Mail"
      → Paste the 16-character code (not your regular password)
   6. Send Alerts To: recipient@email.com
   7. Click "\U0001f4be Save Alert Settings"

\U0001f4f1 SMS Text Alerts:
   1. Check the "\U0001f4f1 SMS Text" checkbox
   2. Fill in SMTP settings (same as email — SMS uses email gateway)
   3. Enter your 10-digit phone number
   4. Select your carrier from the dropdown:
      Xfinity, Verizon, AT&T, T-Mobile, Sprint, Metro,
      Cricket, Boost, Google Fi, Mint, Visible
   5. Click "\U0001f4be Save Alert Settings"

\U0001f517 Webhook:
   1. Check "\U0001f517 Webhook"
   2. Enter the URL to POST JSON alerts to
   3. Works with Slack Incoming Webhooks, Discord, etc.

Testing:
   • Click "\U0001f514 Send Test Alert" to verify all channels
   • A detailed popup shows which channels succeeded/failed

Alert Behavior:
   • Alerts fire after 3 consecutive failures (configurable)
   • 15-minute cooldown prevents notification spam
   • Recovery notifications sent when monitors come back up


\u2699\ufe0f  SETTINGS
───────────────────────────────────────────────

• API Port: Default 8000 (change before starting services)
• Status Page Port: Default 8001
• Probe Concurrency: How many probes run in parallel (default 5)
• Probe Interval: How often monitors are checked (default 60 sec)
• Alert Threshold: Consecutive failures before alerting (default 3)


\u270f\ufe0f  EDITING MONITORS
───────────────────────────────────────────────

In the App (Monitors tab):
   • Double-click any monitor row to edit
   • Click "\u2795 Add Monitor" to create new
   • Select a row and click "\U0001f5d1\ufe0f Delete" to remove

On the Web (Manage page):
   • Go to http://localhost:8001/manage
   • Click \u270f\ufe0f Edit next to any monitor
   • Use the Add New Monitor form at the bottom
   • Click \U0001f5d1\ufe0f to delete


\U0001f4e6  BUILDING THE EXE
───────────────────────────────────────────────

To rebuild the standalone EXE from source:

   pip install pyinstaller
   py windows\\build_exe.py

Output: dist\\TechSentinelMonitor.exe (single file, ~43 MB)
No Python installation needed on the target machine.


\U0001f4be  DATA STORAGE
───────────────────────────────────────────────

• Database: SQLite file created automatically
  (tech_sentinel.db in the app directory)
• Alert Config: alert_config.json (same directory)
• No external database server required
• WAL mode enabled for concurrent read/write


\U0001f6e0\ufe0f  TROUBLESHOOTING
───────────────────────────────────────────────

Port Already in Use:
   → Change the port in Settings before starting
   → Or close the other app using that port

Email/SMS Not Sending:
   → Check the Console tab for error messages
   → Gmail requires App Passwords (not regular passwords)
   → Enable 2-Step Verification on Google first
   → Use "\U0001f514 Send Test Alert" to see detailed errors

Monitors All Showing Down:
   → Check that your PC can reach those IPs
   → Make sure you didn't disconnect a shared switch
   → Only the devices on the disconnected segment go down

EXE Startup Error:
   → Run from source first to see the full error:
     py windows\\run.py
   → Check Windows Defender isn't blocking the app


\U0001f4de  SUPPORT
───────────────────────────────────────────────

Developed by Ronald Goodchild
REGTeches / Bay Area Tech
\u00a9 2026 REGTeches — All Rights Reserved
"""

        manual.insert("1.0", manual_text.strip())
        manual.configure(state="disabled")

        btn_frame = ttk.Frame(dlg, style="Dark.TFrame")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Close", style="Accent.TButton",
                   command=dlg.destroy).pack(side="right", padx=10)

    def _on_close(self):
        if self.api_running:
            if messagebox.askyesno("Quit", "Services are running. Stop and quit?"):
                self._do_stop()
                self.root.after(1000, self.root.destroy)
            return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    # Ensure we can find windows package
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    app = TechSentinelLauncher()
    app.run()


if __name__ == "__main__":
    main()
