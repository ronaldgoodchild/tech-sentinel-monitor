"""
Tech Sentinel Monitor — Windows System Info Agent
===================================================
Lightweight agent that runs on any Windows PC, collects full
system information, and reports it as a heartbeat to the
Tech Sentinel Monitor API.

Requirements:
    pip install requests

Optional (for richer data):
    pip install psutil

Usage:
    python windows_system_agent.py --api-url http://192.168.1.121:8000 --api-key YOUR_KEY
    python windows_system_agent.py --print          # Just show system info
    python windows_system_agent.py --once            # Send once and exit

Created by Ronald Goodchild / REGTeches
"""

import argparse
import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

# ── Optional psutil import ──────────────────────────────────────────────────
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Optional requests import ────────────────────────────────────────────────
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


APP_VERSION = "1.2.0"
AGENT_TYPE = "windows"

# Fix encoding for Windows console (cp1252 can't handle emoji)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Config / Data Paths ───────────────────────────────────────────────────
_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "TechSentinelMonitor",
)
MONITOR_ID_FILE = os.path.join(_DATA_DIR, "agent_monitor_id.txt")
CONFIG_FILE = os.path.join(_DATA_DIR, "agent_config.json")
LOG_FILE = os.path.join(_DATA_DIR, "agent.log")
TASK_NAME = "TechSentinelAgent"


def _load_config() -> dict:
    """Load saved config (api_url, api_key, interval) from JSON file."""
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(api_url: str, api_key: str, interval: int = 60):
    """Save config to JSON file so the agent can run without CLI args."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    cfg = {"api_url": api_url, "api_key": api_key, "interval": interval}
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"  Config saved to: {CONFIG_FILE}")


def _run_cmd(cmd: str, timeout: int = 10) -> str:
    """Run a shell command and return output, hiding the console window."""
    try:
        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW, shell=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _wmic(query: str) -> str:
    """Run a WMIC query."""
    return _run_cmd(f"wmic {query}")


# ── System Info Collectors ──────────────────────────────────────────────────

def get_hostname() -> str:
    return platform.node()


def get_os_version() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "edition": platform.platform(),
        "architecture": platform.machine(),
    }


def get_cpu_info() -> dict:
    info = {
        "processor": platform.processor(),
        "cores_logical": os.cpu_count(),
        "cores_physical": None,
        "usage_percent": None,
        "name": "",
    }

    if HAS_PSUTIL:
        try:
            info["cores_physical"] = psutil.cpu_count(logical=False)
            info["usage_percent"] = psutil.cpu_percent(interval=1)
        except Exception:
            pass

    # Get friendly CPU name from WMI or registry
    try:
        raw = _wmic("cpu get Name /format:list")
        for line in raw.splitlines():
            if line.startswith("Name="):
                info["name"] = line.split("=", 1)[1].strip()
                break
    except Exception:
        pass

    # Fallback: read from registry
    if not info["name"]:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            info["name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            winreg.CloseKey(key)
        except Exception:
            info["name"] = info.get("processor", "Unknown")

    return info


def get_ram_info() -> dict:
    info = {
        "total_gb": None,
        "available_gb": None,
        "used_gb": None,
        "percent_used": None,
    }

    if HAS_PSUTIL:
        try:
            mem = psutil.virtual_memory()
            info["total_gb"] = round(mem.total / (1024**3), 2)
            info["available_gb"] = round(mem.available / (1024**3), 2)
            info["used_gb"] = round(mem.used / (1024**3), 2)
            info["percent_used"] = mem.percent
            return info
        except Exception:
            pass

    # Fallback to WMIC
    try:
        raw = _wmic("OS get TotalVisibleMemorySize,FreePhysicalMemory /format:list")
        total_kb = free_kb = 0
        for line in raw.splitlines():
            if line.startswith("TotalVisibleMemorySize="):
                total_kb = int(line.split("=")[1])
            elif line.startswith("FreePhysicalMemory="):
                free_kb = int(line.split("=")[1])
        if total_kb:
            info["total_gb"] = round(total_kb / (1024 * 1024), 2)
            info["available_gb"] = round(free_kb / (1024 * 1024), 2)
            info["used_gb"] = round((total_kb - free_kb) / (1024 * 1024), 2)
            info["percent_used"] = round(((total_kb - free_kb) / total_kb) * 100, 1)
    except Exception:
        pass

    return info


def get_disk_info() -> list[dict]:
    """Enumerate all drives and their space."""
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        path = f"{letter}:\\"
        if os.path.exists(path):
            try:
                usage = shutil.disk_usage(path)
                drives.append({
                    "drive": f"{letter}:",
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent_used": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
                })
            except (PermissionError, OSError):
                drives.append({"drive": f"{letter}:", "error": "access denied"})
    return drives


def get_network_interfaces() -> list[dict]:
    """Get network interface info."""
    interfaces = []

    if HAS_PSUTIL:
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for name, addr_list in addrs.items():
                iface = {"name": name, "addresses": [], "is_up": False, "speed_mbps": 0}
                if name in stats:
                    iface["is_up"] = stats[name].isup
                    iface["speed_mbps"] = stats[name].speed
                for addr in addr_list:
                    if addr.family == socket.AF_INET:
                        iface["addresses"].append({
                            "type": "IPv4", "address": addr.address,
                            "netmask": addr.netmask,
                        })
                    elif addr.family == socket.AF_INET6:
                        iface["addresses"].append({
                            "type": "IPv6", "address": addr.address,
                        })
                if iface["addresses"]:  # Only include interfaces with addresses
                    interfaces.append(iface)
            return interfaces
        except Exception:
            pass

    # Fallback: parse ipconfig
    try:
        raw = _run_cmd("ipconfig /all")
        current = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith(" ") and line.endswith(":") and not line.startswith("Windows"):
                # Reset — sometimes headers aren't indented
                pass
            if "adapter" in line.lower() and line.endswith(":"):
                if current and current.get("addresses"):
                    interfaces.append(current)
                current = {"name": line.rstrip(":"), "addresses": []}
            elif current and "IPv4 Address" in line and ":" in line:
                addr = line.split(":", 1)[1].strip().rstrip("(Preferred)")
                current["addresses"].append({"type": "IPv4", "address": addr})
            elif current and "IPv6 Address" in line and ":" in line:
                addr = line.split(":", 1)[1].strip().rstrip("(Preferred)")
                current["addresses"].append({"type": "IPv6", "address": addr})
        if current and current.get("addresses"):
            interfaces.append(current)
    except Exception:
        pass

    return interfaces


def get_system_uptime() -> dict:
    """Get system uptime."""
    try:
        tick = ctypes.windll.kernel32.GetTickCount64()
        uptime_secs = tick / 1000
        days = int(uptime_secs // 86400)
        hours = int((uptime_secs % 86400) // 3600)
        mins = int((uptime_secs % 3600) // 60)
        return {
            "uptime_seconds": int(uptime_secs),
            "uptime_human": f"{days}d {hours}h {mins}m",
            "boot_time": None,
        }
    except Exception:
        return {"uptime_seconds": 0, "uptime_human": "unknown"}

    if HAS_PSUTIL:
        try:
            boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
            return {
                "uptime_seconds": int((datetime.now(timezone.utc) - boot).total_seconds()),
                "uptime_human": f"{days}d {hours}h {mins}m",
                "boot_time": boot.isoformat(),
            }
        except Exception:
            pass


def get_gpu_info() -> list[dict]:
    """Get GPU information."""
    gpus = []
    try:
        raw = _wmic("path win32_VideoController get Name,DriverVersion,AdapterRAM /format:list")
        gpu = {}
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("Name="):
                gpu["name"] = line.split("=", 1)[1]
            elif line.startswith("DriverVersion="):
                gpu["driver_version"] = line.split("=", 1)[1]
            elif line.startswith("AdapterRAM="):
                try:
                    ram = int(line.split("=", 1)[1])
                    gpu["vram_mb"] = round(ram / (1024 * 1024))
                except ValueError:
                    pass
            if not line and gpu:
                gpus.append(gpu)
                gpu = {}
        if gpu:
            gpus.append(gpu)
    except Exception:
        pass
    return gpus


def get_installed_software_count() -> int:
    """Get count of installed programs."""
    try:
        raw = _run_cmd(
            'powershell -Command "(Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\'
            'CurrentVersion\\Uninstall\\* | Measure-Object).Count"',
            timeout=15,
        )
        return int(raw.strip()) if raw.strip().isdigit() else 0
    except Exception:
        return 0


# ── Structured Command Handlers (for web UI features) ─────────────────────

def handle_structured_command(command: str) -> str:
    """Handle __ts: prefixed structured commands, return JSON."""
    parts = command.split(":", 2)
    if len(parts) < 2:
        return json.dumps({"error": "Invalid structured command"})

    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    handlers = {
        "services": _ts_services,
        "processes": _ts_processes,
        "software": _ts_software,
        "eventlog": _ts_eventlog,
        "ls": lambda: _ts_ls(arg),
        "download": lambda: _ts_download(arg),
        "kill": lambda: _ts_kill(arg),
        "service": lambda: _ts_service(arg),
    }

    handler = handlers.get(action)
    if not handler:
        return json.dumps({"error": f"Unknown command: {action}"})

    try:
        result = handler()
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _ts_services() -> dict:
    """Get Windows services list."""
    services = []
    if HAS_PSUTIL:
        try:
            for svc in psutil.win_service_iter():
                try:
                    info = svc.as_dict()
                    services.append({
                        "name": info.get("name", ""),
                        "display_name": info.get("display_name", ""),
                        "status": info.get("status", ""),
                        "start_type": info.get("start_type", ""),
                        "pid": info.get("pid", None),
                    })
                except Exception:
                    pass
            services.sort(key=lambda s: s.get("display_name", "").lower())
            return {"services": services, "count": len(services)}
        except Exception:
            pass

    # Fallback: use sc query
    try:
        raw = _run_cmd("sc query state= all", timeout=30)
        svc = {}
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("SERVICE_NAME:"):
                if svc.get("name"):
                    services.append(svc)
                svc = {"name": line.split(":", 1)[1].strip()}
            elif line.startswith("DISPLAY_NAME:"):
                svc["display_name"] = line.split(":", 1)[1].strip()
            elif line.startswith("STATE"):
                # STATE              : 4  RUNNING
                state_part = line.split(":", 1)[1].strip()
                if "RUNNING" in state_part:
                    svc["status"] = "running"
                elif "STOPPED" in state_part:
                    svc["status"] = "stopped"
                elif "PAUSED" in state_part:
                    svc["status"] = "paused"
                else:
                    svc["status"] = state_part.split()[-1].lower() if state_part.split() else "unknown"
        if svc.get("name"):
            services.append(svc)
        services.sort(key=lambda s: s.get("display_name", s.get("name", "")).lower())
        return {"services": services, "count": len(services)}
    except Exception as e:
        return {"error": str(e), "services": []}


def _ts_processes() -> dict:
    """Get running processes."""
    processes = []
    if HAS_PSUTIL:
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'username', 'status']):
                try:
                    info = proc.info
                    mem_mb = round(info['memory_info'].rss / (1024 * 1024), 1) if info.get('memory_info') else 0
                    processes.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu_percent": info.get('cpu_percent', 0) or 0,
                        "memory_mb": mem_mb,
                        "username": info.get('username', ''),
                        "status": info.get('status', ''),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            processes.sort(key=lambda p: p.get("memory_mb", 0), reverse=True)
            return {"processes": processes[:100], "total": len(processes)}
        except Exception:
            pass

    # Fallback: tasklist
    try:
        raw = _run_cmd("tasklist /FO CSV /NH", timeout=15)
        for line in raw.splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 5:
                try:
                    mem_str = parts[4].replace('"', '').replace(',', '').replace(' K', '').replace(' ', '')
                    mem_kb = int(mem_str) if mem_str.isdigit() else 0
                    processes.append({
                        "pid": int(parts[1].replace('"', '')) if parts[1].replace('"', '').isdigit() else 0,
                        "name": parts[0],
                        "memory_mb": round(mem_kb / 1024, 1),
                        "cpu_percent": 0,
                        "username": "",
                        "status": "running",
                    })
                except (ValueError, IndexError):
                    pass
        processes.sort(key=lambda p: p.get("memory_mb", 0), reverse=True)
        return {"processes": processes[:100], "total": len(processes)}
    except Exception as e:
        return {"error": str(e), "processes": []}


def _ts_software() -> dict:
    """Get installed software list."""
    software = []
    try:
        import winreg
        paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        seen = set()
        for hive, path in paths:
            try:
                key = winreg.OpenKey(hive, path)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        try:
                            name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                        except FileNotFoundError:
                            continue
                        if name in seen:
                            continue
                        seen.add(name)
                        version = ""
                        publisher = ""
                        install_date = ""
                        size = ""
                        try:
                            version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                        except FileNotFoundError:
                            pass
                        try:
                            publisher = winreg.QueryValueEx(subkey, "Publisher")[0]
                        except FileNotFoundError:
                            pass
                        try:
                            install_date = winreg.QueryValueEx(subkey, "InstallDate")[0]
                        except FileNotFoundError:
                            pass
                        try:
                            size_kb = winreg.QueryValueEx(subkey, "EstimatedSize")[0]
                            size = f"{round(size_kb / 1024, 1)} MB"
                        except (FileNotFoundError, TypeError):
                            pass
                        software.append({
                            "name": name,
                            "version": version,
                            "publisher": publisher,
                            "install_date": install_date,
                            "size": size,
                        })
                        winreg.CloseKey(subkey)
                    except (WindowsError, OSError):
                        continue
                winreg.CloseKey(key)
            except (WindowsError, OSError):
                continue
        software.sort(key=lambda s: s.get("name", "").lower())
        return {"software": software, "count": len(software)}
    except Exception as e:
        return {"error": str(e), "software": []}


def _ts_eventlog() -> dict:
    """Get recent Windows Event Log entries (errors and warnings)."""
    events = []
    try:
        # PowerShell to get recent error/warning events
        ps_cmd = (
            'powershell -Command "'
            "Get-EventLog -LogName System -Newest 50 -EntryType Error,Warning "
            "| Select-Object TimeGenerated,EntryType,Source,Message "
            "| ConvertTo-Json -Compress"
            '"'
        )
        raw = _run_cmd(ps_cmd, timeout=30)
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            for evt in data:
                # PowerShell dates come as /Date(ms)/
                time_str = evt.get("TimeGenerated", "")
                if "/Date(" in str(time_str):
                    try:
                        ms = int(str(time_str).split("(")[1].split(")")[0].split("-")[0].split("+")[0])
                        time_str = datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                events.append({
                    "time": str(time_str),
                    "level": str(evt.get("EntryType", "")),
                    "source": str(evt.get("Source", "")),
                    "message": str(evt.get("Message", ""))[:200],
                })
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"error": str(e), "events": []}


def _ts_ls(path: str) -> dict:
    """List directory contents."""
    if not path:
        path = "C:\\"
    try:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"error": f"Path not found: {path}", "files": []}
        if not os.path.isdir(path):
            return {"error": f"Not a directory: {path}", "files": []}

        entries = []
        try:
            for entry in os.scandir(path):
                try:
                    stat = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size": stat.st_size if not entry.is_dir() else 0,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except (PermissionError, OSError):
                    entries.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir() if hasattr(entry, 'is_dir') else False,
                        "size": 0,
                        "modified": "",
                        "error": "access denied",
                    })
        except PermissionError:
            return {"error": f"Access denied: {path}", "path": path, "files": []}

        # Sort: directories first, then by name
        entries.sort(key=lambda e: (not e.get("is_dir", False), e.get("name", "").lower()))
        parent = os.path.dirname(path) if path != os.path.dirname(path) else ""
        return {"path": path, "parent": parent, "files": entries, "count": len(entries)}
    except Exception as e:
        return {"error": str(e), "path": path, "files": []}


def _ts_download(path: str) -> dict:
    """Read a file and return its content as base64."""
    import base64
    try:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        if os.path.isdir(path):
            return {"error": "Cannot download a directory"}
        size = os.path.getsize(path)
        if size > 10 * 1024 * 1024:  # 10MB limit
            return {"error": f"File too large: {size / (1024*1024):.1f} MB (max 10 MB)"}
        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")
        return {"path": path, "filename": os.path.basename(path), "size": size,
                "content_base64": content}
    except PermissionError:
        return {"error": f"Access denied: {path}"}
    except Exception as e:
        return {"error": str(e)}


def _ts_kill(pid_str: str) -> dict:
    """Kill a process by PID."""
    try:
        pid = int(pid_str)
        if pid <= 4:
            return {"error": "Cannot kill system process"}
        if HAS_PSUTIL:
            proc = psutil.Process(pid)
            name = proc.name()
            proc.kill()
            return {"success": True, "message": f"Killed process {name} (PID {pid})"}
        else:
            result = _run_cmd(f"taskkill /PID {pid} /F", timeout=10)
            return {"success": True, "message": result or f"Kill signal sent to PID {pid}"}
    except (psutil.NoSuchProcess if HAS_PSUTIL else Exception):
        return {"error": f"Process {pid_str} not found"}
    except (psutil.AccessDenied if HAS_PSUTIL else PermissionError):
        return {"error": f"Access denied — cannot kill PID {pid_str}"}
    except Exception as e:
        return {"error": str(e)}


def _ts_service(arg: str) -> dict:
    """Manage a Windows service: start, stop, restart."""
    parts = arg.split(":", 1)
    if len(parts) != 2:
        return {"error": "Usage: __ts:service:ACTION:SERVICE_NAME"}
    action, svc_name = parts[0], parts[1]

    if action not in ("start", "stop", "restart"):
        return {"error": f"Invalid action: {action}. Use start, stop, or restart."}

    try:
        if action == "restart":
            _run_cmd(f'net stop "{svc_name}"', timeout=30)
            import time as _t
            _t.sleep(2)
            result = _run_cmd(f'net start "{svc_name}"', timeout=30)
        elif action == "start":
            result = _run_cmd(f'net start "{svc_name}"', timeout=30)
        elif action == "stop":
            result = _run_cmd(f'net stop "{svc_name}"', timeout=30)
        else:
            result = ""

        return {"success": True, "action": action, "service": svc_name,
                "message": result or f"Service {svc_name} {action} command sent"}
    except Exception as e:
        return {"error": str(e)}


def get_local_ip() -> str:
    """Get primary local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


# ── Main Collection ─────────────────────────────────────────────────────────

def collect_system_info() -> dict:
    """Collect all system information into a single dict."""
    return {
        "agent_version": APP_VERSION,
        "agent_type": AGENT_TYPE,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "hostname": get_hostname(),
        "local_ip": get_local_ip(),
        "os": get_os_version(),
        "cpu": get_cpu_info(),
        "ram": get_ram_info(),
        "disks": get_disk_info(),
        "network_interfaces": get_network_interfaces(),
        "uptime": get_system_uptime(),
        "gpu": get_gpu_info(),
        "python_version": sys.version,
        "has_psutil": HAS_PSUTIL,
        "installed_software_count": get_installed_software_count(),
    }


# ── API Communication ──────────────────────────────────────────────────────

def get_or_create_monitor(api_url: str, api_key: str, hostname: str) -> str | None:
    """Register this agent as a heartbeat monitor, return monitor_id."""
    if not HAS_REQUESTS:
        print("ERROR: 'requests' package required. Install: pip install requests")
        return None

    headers = {"X-TS-API-Key": api_key}
    external_id = f"sys-agent-win-{hostname}"

    # Find or create tenant
    try:
        resp = requests.get(f"{api_url}/api/v1/tenants/", headers=headers, timeout=10)
        tenants = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"ERROR: Cannot reach API at {api_url}: {e}")
        return None

    if not tenants:
        print("ERROR: No tenants found. Create a tenant in the launcher GUI first.")
        return None

    tenant_id = tenants[0]["id"]

    # Create or update monitor
    try:
        payload = {
            "tenant_id": tenant_id,
            "name": f"💻 {hostname} (Agent)",
            "monitor_type": "heartbeat",
            "target": f"system-agent://{hostname}",
            "interval_seconds": 60,
            "timeout_seconds": 120,
            "external_id": external_id,
        }
        resp = requests.post(
            f"{api_url}/api/v1/monitors/",
            json=payload, headers=headers, timeout=10,
        )
        if resp.status_code in (200, 201):
            monitor = resp.json()
            monitor_id = monitor["id"]
            print(f"Registered as monitor: {monitor_id}")
            return monitor_id
        else:
            print(f"ERROR: Failed to create monitor: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"ERROR: Failed to register: {e}")

    return None


def send_heartbeat(api_url: str, api_key: str, monitor_id: str, system_info: dict) -> tuple[bool, list, int]:
    """Send heartbeat with system info payload. Returns (success, messages, http_status_code).

    Returns http_status_code=0 on network/connection errors.
    Returns http_status_code=404 when the monitor no longer exists on the server
    (e.g. after the server DB was wiped) — caller should re-register in that case.
    """
    try:
        resp = requests.post(
            f"{api_url}/api/v1/heartbeat/{monitor_id}",
            json={"system_info": system_info},
            headers={"X-TS-API-Key": api_key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            messages = data.get("messages", [])
            return True, messages, 200
        return False, [], resp.status_code
    except Exception as e:
        print(f"Heartbeat failed: {e}")
        return False, [], 0


# ── Remote Command Execution ──────────────────────────────────────────────

# Commands that are blocked for safety (destructive operations)
BLOCKED_COMMANDS = [
    "format", "del /s", "rd /s", "rmdir /s", "shutdown", "restart",
    "reg delete", "bcdedit", "diskpart",
]


def _is_command_safe(cmd: str) -> bool:
    """Basic safety check — block obviously destructive commands."""
    cmd_lower = cmd.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if cmd_lower.startswith(blocked):
            return False
    return True


def poll_and_execute_commands(api_url: str, api_key: str, monitor_id: str):
    """Poll for pending commands and execute them."""
    try:
        resp = requests.get(
            f"{api_url}/api/v1/monitors/{monitor_id}/commands/pending",
            headers={"X-TS-API-Key": api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            return
        commands = resp.json()
        if not commands:
            return

        for cmd in commands:
            cmd_id = cmd["id"]
            command = cmd["command"]
            print(f"  📥 Remote command: {command}")

            # Safety check
            if not _is_command_safe(command):
                print(f"  ⛔ BLOCKED (unsafe): {command}")
                requests.post(
                    f"{api_url}/api/v1/commands/{cmd_id}/result",
                    json={"output": f"BLOCKED: Command '{command}' is not allowed for safety reasons.",
                          "exit_code": -1, "status": "failed"},
                    headers={"X-TS-API-Key": api_key}, timeout=10,
                )
                continue

            # Mark as started
            try:
                requests.post(
                    f"{api_url}/api/v1/commands/{cmd_id}/start",
                    headers={"X-TS-API-Key": api_key}, timeout=10,
                )
            except Exception:
                pass

            # Check for structured command
            if command.startswith("__ts:"):
                try:
                    output = handle_structured_command(command)
                    exit_code = 0
                    status = "completed"
                    print(f"  ✅ Structured command completed")
                except Exception as e:
                    output = json.dumps({"error": str(e)})
                    exit_code = -1
                    status = "failed"
                    print(f"  ❌ Structured command error: {e}")

                try:
                    requests.post(
                        f"{api_url}/api/v1/commands/{cmd_id}/result",
                        json={"output": output, "exit_code": exit_code, "status": status},
                        headers={"X-TS-API-Key": api_key}, timeout=10,
                    )
                except Exception as e:
                    print(f"  ⚠️ Failed to report result: {e}")
                continue

            # Execute
            try:
                CREATE_NO_WINDOW = 0x08000000
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=120,
                    creationflags=CREATE_NO_WINDOW, shell=True,
                )
                output = result.stdout
                if result.stderr:
                    output += "\n--- STDERR ---\n" + result.stderr
                # Truncate to 50KB
                if len(output) > 50000:
                    output = output[:50000] + "\n... (truncated)"
                exit_code = result.returncode
                status = "completed"
                print(f"  ✅ Completed (exit {exit_code})")
            except subprocess.TimeoutExpired:
                output = "Command timed out after 120 seconds"
                exit_code = -1
                status = "failed"
                print(f"  ⏰ Timed out")
            except Exception as e:
                output = f"Error executing command: {e}"
                exit_code = -1
                status = "failed"
                print(f"  ❌ Error: {e}")

            # Report result
            try:
                requests.post(
                    f"{api_url}/api/v1/commands/{cmd_id}/result",
                    json={"output": output, "exit_code": exit_code, "status": status},
                    headers={"X-TS-API-Key": api_key}, timeout=10,
                )
            except Exception as e:
                print(f"  ⚠️ Failed to report result: {e}")

    except Exception as e:
        if "Connection" not in str(e):
            print(f"  ⚠️ Command poll error: {e}")


def _load_monitor_id() -> str | None:
    try:
        if os.path.exists(MONITOR_ID_FILE):
            with open(MONITOR_ID_FILE, "r") as f:
                return f.read().strip() or None
    except Exception:
        pass
    return None


def _save_monitor_id(mid: str):
    os.makedirs(os.path.dirname(MONITOR_ID_FILE), exist_ok=True)
    with open(MONITOR_ID_FILE, "w") as f:
        f.write(mid)


# ── Service Install / Uninstall ────────────────────────────────────────────

def _is_admin() -> bool:
    """Check if the current process has Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _find_real_python() -> str:
    """Return a real python.exe path that schtasks can launch.

    Windows Store Python (sys.executable inside WindowsApps\\) is an app-execution
    alias — a stub that redirects to the Store app.  Task Scheduler cannot resolve
    those aliases, so the task silently fails with 'file not found'.

    Resolution order:
      1. sys.executable — if it is NOT the Store alias, use it directly.
      2. py.exe (Python Launcher) — always a real binary at %WINDIR%\\py.exe.
      3. `where python` — find the first non-Store python.exe on PATH.
      4. Registry — check HKCU/HKLM for installed Python core paths.
    """
    current = sys.executable

    # Not a Store alias → use as-is
    if "WindowsApps" not in current and os.path.isfile(current):
        return current

    print("  ⚠️  Windows Store Python detected — locating real python.exe...")

    # 1. py.exe launcher (most reliable — installed alongside any Python)
    py_launcher = shutil.which("py")
    if py_launcher and "WindowsApps" not in py_launcher and os.path.isfile(py_launcher):
        print(f"  ✅ Using Python Launcher: {py_launcher}")
        return py_launcher

    # 2. `where python` — skip Store stubs
    try:
        result = subprocess.run(
            ["where", "python"], capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line and "WindowsApps" not in line and os.path.isfile(line):
                print(f"  ✅ Found via PATH: {line}")
                return line
    except Exception:
        pass

    # 3. Registry — HKCU then HKLM, newest version first
    import winreg
    for version in ["3.13", "3.12", "3.11", "3.10"]:
        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for arch in ["", "\\Wow6432Node"]:
                key_path = f"SOFTWARE{arch}\\Python\\PythonCore\\{version}\\InstallPath"
                try:
                    with winreg.OpenKey(hive, key_path) as k:
                        install_dir = winreg.QueryValue(k, "")
                        exe = os.path.join(install_dir.strip(), "python.exe")
                        if os.path.isfile(exe):
                            print(f"  ✅ Found via registry: {exe}")
                            return exe
                except Exception:
                    pass

    # Give up — return original and let schtasks report the error clearly
    print(f"  ⚠️  Could not find a non-Store python.exe — using: {current}")
    return current


def _install_service(api_url: str, api_key: str, interval: int = 60):
    """Install the agent as a Windows Scheduled Task that runs at startup."""
    # Must run as Administrator to create scheduled tasks
    if not _is_admin():
        print("\n  ❌ Administrator rights required to install the scheduled task.")
        print("  ➡️  Right-click Command Prompt → 'Run as administrator', then re-run:")
        print(f"       python \"{os.path.abspath(__file__)}\" "
              f"--api-url {api_url} --api-key {api_key} --install")
        return

    # Save config first so the agent can self-configure on boot
    _save_config(api_url, api_key, interval)

    # Find a real python.exe (handles Windows Store alias)
    python_exe = _find_real_python()
    agent_script = os.path.abspath(__file__)

    # Build the command — use --service mode (headless, reads config file)
    cmd_line = f'"{python_exe}" "{agent_script}" --service'

    print(f"\n{'='*60}")
    print("  Installing Tech Sentinel Agent as Windows Service")
    print(f"{'='*60}")
    print(f"  Python:   {python_exe}")
    print(f"  Script:   {agent_script}")
    print(f"  API URL:  {api_url}")
    print(f"  Interval: {interval}s")
    print(f"  Config:   {CONFIG_FILE}")
    print(f"  Log:      {LOG_FILE}")

    # Remove existing task if present
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, creationflags=0x08000000,
    )

    # Create scheduled task that runs at logon, restarts on failure
    # Using XML for more control (restart on failure, hidden window)
    xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Tech Sentinel Monitor Agent - System monitoring and heartbeat service by REGTeches</Description>
    <Author>REGTeches / Ronald Goodchild</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT30S</Delay>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions>
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{agent_script}" --service</Arguments>
      <WorkingDirectory>{os.path.dirname(agent_script)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    # Write XML to temp file
    xml_path = os.path.join(_DATA_DIR, "task_config.xml")
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml_content)

    # Import task via schtasks
    result = subprocess.run(
        ["schtasks", "/create", "/tn", TASK_NAME, "/xml", xml_path, "/f"],
        capture_output=True, text=True, creationflags=0x08000000,
    )

    if result.returncode == 0:
        print(f"\n  ✅ Service installed successfully!")
        print(f"  Task Name: {TASK_NAME}")
        print(f"\n  The agent will:")
        print(f"    • Start automatically when you log in")
        print(f"    • Start automatically at boot")
        print(f"    • Auto-restart if it crashes (every 1 min)")
        print(f"    • Run in the background (no console window)")
        print(f"\n  To start it now:")
        print(f"    schtasks /run /tn {TASK_NAME}")
        print(f"\n  To check status:")
        print(f"    schtasks /query /tn {TASK_NAME}")
        print(f"\n  To uninstall:")
        print(f"    python {os.path.basename(__file__)} --uninstall")

        # Start it right now
        print(f"\n  Starting agent now...")
        subprocess.run(
            ["schtasks", "/run", "/tn", TASK_NAME],
            capture_output=True, creationflags=0x08000000,
        )
        print(f"  ✅ Agent is running!")
    else:
        print(f"\n  ❌ Install failed: {result.stderr.strip()}")
        print(f"  Try running as Administrator.")

    # Cleanup XML
    try:
        os.remove(xml_path)
    except Exception:
        pass


def _uninstall_service():
    """Remove the scheduled task."""
    print(f"\n{'='*60}")
    print("  Uninstalling Tech Sentinel Agent")
    print(f"{'='*60}")

    # Stop it first
    subprocess.run(
        ["schtasks", "/end", "/tn", TASK_NAME],
        capture_output=True, creationflags=0x08000000,
    )

    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True, creationflags=0x08000000,
    )

    if result.returncode == 0:
        print(f"  ✅ Service uninstalled (task '{TASK_NAME}' removed)")
    else:
        print(f"  ⚠️  Task may not exist: {result.stderr.strip()}")

    print(f"\n  Config file kept at: {CONFIG_FILE}")
    print(f"  Log file kept at: {LOG_FILE}")
    print(f"  To remove all data: delete {_DATA_DIR}")


def _service_status():
    """Show current service status."""
    print(f"\n{'='*60}")
    print("  Tech Sentinel Agent — Status")
    print(f"{'='*60}")

    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"],
        capture_output=True, text=True, creationflags=0x08000000,
    )

    if result.returncode == 0:
        # Parse out the important fields
        for line in result.stdout.splitlines():
            line = line.strip()
            if any(k in line for k in ["Status:", "Last Run Time:", "Next Run Time:",
                                        "Last Result:", "Task Name:"]):
                print(f"  {line}")
    else:
        print(f"  ❌ Task '{TASK_NAME}' not found. Agent is not installed.")

    cfg = _load_config()
    if cfg:
        print(f"\n  Config:")
        print(f"    API URL:  {cfg.get('api_url', '?')}")
        print(f"    API Key:  {cfg.get('api_key', '?')[:12]}...")
        print(f"    Interval: {cfg.get('interval', 60)}s")
    else:
        print(f"\n  No config file found at {CONFIG_FILE}")

    if os.path.exists(LOG_FILE):
        size = os.path.getsize(LOG_FILE)
        print(f"\n  Log: {LOG_FILE} ({size:,} bytes)")
        # Show last 5 lines
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                print(f"  Last {min(5, len(lines))} log entries:")
                for line in lines[-5:]:
                    print(f"    {line.rstrip()}")
        except Exception:
            pass


def _setup_file_logging():
    """Redirect stdout/stderr to log file for service mode."""
    import logging
    os.makedirs(_DATA_DIR, exist_ok=True)

    # Rotate log if > 5MB
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 5 * 1024 * 1024:
            backup = LOG_FILE + ".old"
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(LOG_FILE, backup)
    except Exception:
        pass

    log_fh = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    sys.stdout = log_fh
    sys.stderr = log_fh


# ── Main Entry Point ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Tech Sentinel Monitor — Windows System Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  First-time setup (interactive):
    python windows_system_agent.py --api-url http://192.168.1.121:8000 --api-key YOUR_KEY --install

  Run manually (foreground):
    python windows_system_agent.py --api-url http://192.168.1.121:8000 --api-key YOUR_KEY

  Run from saved config:
    python windows_system_agent.py

  Check status:
    python windows_system_agent.py --status

  Uninstall:
    python windows_system_agent.py --uninstall

Created by Ronald Goodchild / REGTeches""",
    )
    parser.add_argument("--api-url", default="",
                        help="Tech Sentinel API URL (e.g. http://192.168.1.121:8000)")
    parser.add_argument("--api-key", default="",
                        help="API key for authentication")
    parser.add_argument("--interval", type=int, default=0,
                        help="Heartbeat interval in seconds (default: 60)")
    parser.add_argument("--once", action="store_true",
                        help="Collect and send once, then exit")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Just print system info as JSON")
    parser.add_argument("--install", action="store_true",
                        help="Install as auto-start Windows service (Task Scheduler)")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the Windows service")
    parser.add_argument("--status", action="store_true",
                        help="Show service status and config")
    parser.add_argument("--service", action="store_true",
                        help="Run in service mode (headless, logs to file)")
    args = parser.parse_args()

    # ── Status check ──
    if args.status:
        _service_status()
        return

    # ── Uninstall ──
    if args.uninstall:
        _uninstall_service()
        return

    # ── Service mode (headless, called by Task Scheduler) ──
    if args.service:
        _setup_file_logging()

    print("=" * 60)
    print("  Tech Sentinel Monitor — Windows System Agent v" + APP_VERSION)
    print("  Created by Ronald Goodchild / REGTeches")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Print-only mode
    if args.print_only:
        info = collect_system_info()
        print(json.dumps(info, indent=2, default=str))
        return

    if not HAS_REQUESTS:
        print("\nERROR: 'requests' package is required.")
        print("Install it with:  pip install requests")
        sys.exit(1)

    # Load saved config and merge with CLI args (CLI args override)
    saved_cfg = _load_config()
    api_url = args.api_url or saved_cfg.get("api_url", "")
    api_key = args.api_key or saved_cfg.get("api_key", "")
    interval = args.interval or saved_cfg.get("interval", 60)

    if not api_url or not api_key:
        print("\nERROR: --api-url and --api-key are required.")
        print("  Either provide them on the command line, or run --install first.")
        print(f"\n  Saved config location: {CONFIG_FILE}")
        if saved_cfg:
            print(f"  Found config with: api_url={saved_cfg.get('api_url','?')}")
        else:
            print("  No saved config found.")
        sys.exit(1)

    # Save config for future runs (so --service mode can find it)
    _save_config(api_url, api_key, interval)

    # ── Install as service ──
    if args.install:
        _install_service(api_url, api_key, interval)
        return

    hostname = get_hostname()
    print(f"\nHostname: {hostname}")
    print(f"API:      {api_url}")
    print(f"Interval: {interval}s")
    print(f"Mode:     {'Service (headless)' if args.service else 'Interactive'}")

    # Get or register monitor
    monitor_id = _load_monitor_id()
    if not monitor_id:
        print("\nRegistering with Tech Sentinel...")
        monitor_id = get_or_create_monitor(api_url, api_key, hostname)
        if not monitor_id:
            sys.exit(1)
        _save_monitor_id(monitor_id)
    else:
        print(f"Monitor ID: {monitor_id} (cached)")

    # Heartbeat loop
    print(f"\nStarting heartbeat loop (every {interval}s)...")
    if not args.service:
        print("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        cycle += 1
        try:
            info = collect_system_info()
            ok, messages, http_code = send_heartbeat(api_url, api_key, monitor_id, info)

            # If the server says the monitor doesn't exist (404), the DB was likely
            # wiped or the server was reinstalled. Clear the cached ID and re-register
            # immediately so the agent comes back online without manual intervention.
            if not ok and http_code == 404:
                print(f"[WARN] Monitor {monitor_id} not found on server (404). Re-registering...")
                try:
                    os.remove(MONITOR_ID_FILE)
                except Exception:
                    pass
                monitor_id = get_or_create_monitor(api_url, api_key, hostname)
                if monitor_id:
                    _save_monitor_id(monitor_id)
                    print(f"Re-registered as monitor: {monitor_id}")
                    # Retry heartbeat immediately with new ID
                    ok, messages, http_code = send_heartbeat(api_url, api_key, monitor_id, info)
                else:
                    print("[ERROR] Re-registration failed. Will retry next cycle.")

            hb_status = "OK" if ok else "FAIL"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S" if args.service else "%H:%M:%S")
            ram = info["ram"]
            cpu = info["cpu"]
            print(
                f"[{ts}] #{cycle} {hb_status} | "
                f"CPU: {cpu.get('usage_percent', '?')}% | "
                f"RAM: {ram.get('percent_used', '?')}% "
                f"({ram.get('used_gb', '?')}/{ram.get('total_gb', '?')} GB) | "
                f"Disks: {len(info['disks'])}"
            )
            # Flush for service mode log
            if args.service:
                sys.stdout.flush()

            # Display any pending messages from the server
            for msg in messages:
                msg_type = msg.get("msg_type", "info")
                msg_text = msg.get("message", "")
                msg_id = msg.get("id", "")
                type_icons = {"info": "💬", "warning": "⚠️", "alert": "🚨"}
                print(f"  {type_icons.get(msg_type, '💬')} MESSAGE ({msg_type}): {msg_text}")

                # Show Windows popup for alert/warning messages
                if msg_type in ("alert", "warning"):
                    try:
                        import ctypes as _ct
                        title = "Tech Sentinel Alert" if msg_type == "alert" else "Tech Sentinel Message"
                        icon = 0x30 if msg_type == "alert" else 0x40
                        _ct.windll.user32.MessageBoxW(0, msg_text, title, icon)
                    except Exception:
                        pass

                # Mark as delivered
                if msg_id:
                    try:
                        requests.post(
                            f"{api_url}/api/v1/messages/{msg_id}/delivered",
                            headers={"X-TS-API-Key": api_key}, timeout=5,
                        )
                    except Exception:
                        pass

            # Poll for remote commands
            poll_and_execute_commands(api_url, api_key, monitor_id)

        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            if args.service:
                sys.stdout.flush()

        if args.once:
            break

        # Poll for commands more frequently than heartbeats
        # Sleep in 5-second chunks, checking for commands each time
        elapsed = 0
        while elapsed < interval:
            try:
                time.sleep(min(5, interval - elapsed))
                elapsed += 5
                # Check for commands between heartbeats
                if elapsed < interval:
                    poll_and_execute_commands(api_url, api_key, monitor_id)
            except KeyboardInterrupt:
                print("\nStopped by user.")
                sys.exit(0)


if __name__ == "__main__":
    main()
