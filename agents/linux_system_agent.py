#!/usr/bin/env python3
"""
Tech Sentinel Monitor — Linux System Info Agent
=================================================
Lightweight agent that runs on any Linux machine, collects full
system information, and reports it as a heartbeat to the
Tech Sentinel Monitor API.

Requirements:
    pip install requests

Optional (for richer data):
    pip install psutil

Usage:
    python3 linux_system_agent.py --api-url http://192.168.1.121:8000 --api-key YOUR_KEY
    python3 linux_system_agent.py --print          # Just show system info
    python3 linux_system_agent.py --once            # Send once and exit

Created by Ronald Goodchild / REGTeches
"""

import argparse
import json
import os
import platform
import re
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
AGENT_TYPE = "linux"

# ── Config / Data Paths ───────────────────────────────────────────────────
_DATA_DIR = os.path.expanduser("~/.config/tech-sentinel")
MONITOR_ID_FILE = os.path.join(_DATA_DIR, "agent_monitor_id.txt")
CONFIG_FILE = os.path.join(_DATA_DIR, "agent_config.json")
LOG_FILE = os.path.join(_DATA_DIR, "agent.log")
SERVICE_NAME = "tech-sentinel-agent"


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(api_url: str, api_key: str, interval: int = 60):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_url": api_url, "api_key": api_key, "interval": interval}, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)  # protect the API key
    print(f"  Config saved to: {CONFIG_FILE}")


def _run_cmd(cmd: str, timeout: int = 10) -> str:
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _read_file(path: str) -> str:
    """Read a file, return empty string on error."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return ""


# ── System Info Collectors ──────────────────────────────────────────────────

def get_hostname() -> str:
    hostname = _read_file("/etc/hostname")
    return hostname if hostname else platform.node()


def get_os_version() -> dict:
    info = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "architecture": platform.machine(),
        "distro": "",
        "distro_version": "",
    }

    # Parse /etc/os-release for distro info
    os_release = _read_file("/etc/os-release")
    if os_release:
        for line in os_release.splitlines():
            if line.startswith("PRETTY_NAME="):
                info["distro"] = line.split("=", 1)[1].strip('"')
            elif line.startswith("VERSION_ID="):
                info["distro_version"] = line.split("=", 1)[1].strip('"')

    return info


def get_cpu_info() -> dict:
    info = {
        "name": "",
        "cores_logical": os.cpu_count(),
        "cores_physical": None,
        "usage_percent": None,
    }

    if HAS_PSUTIL:
        try:
            info["cores_physical"] = psutil.cpu_count(logical=False)
            info["usage_percent"] = psutil.cpu_percent(interval=1)
        except Exception:
            pass

    # Get CPU name from /proc/cpuinfo
    cpuinfo = _read_file("/proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                info["name"] = line.split(":", 1)[1].strip()
                break

    # Physical cores from /proc if psutil unavailable
    if info["cores_physical"] is None and cpuinfo:
        core_ids = set()
        for line in cpuinfo.splitlines():
            if line.startswith("core id"):
                core_ids.add(line.split(":", 1)[1].strip())
        if core_ids:
            info["cores_physical"] = len(core_ids)

    # CPU usage from /proc/stat if psutil unavailable
    if info["usage_percent"] is None:
        try:
            stat1 = _read_file("/proc/stat").splitlines()[0].split()
            time.sleep(0.5)
            stat2 = _read_file("/proc/stat").splitlines()[0].split()
            idle1 = int(stat1[4])
            idle2 = int(stat2[4])
            total1 = sum(int(x) for x in stat1[1:])
            total2 = sum(int(x) for x in stat2[1:])
            idle_diff = idle2 - idle1
            total_diff = total2 - total1
            if total_diff > 0:
                info["usage_percent"] = round((1 - idle_diff / total_diff) * 100, 1)
        except Exception:
            pass

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

    # Parse /proc/meminfo
    meminfo = _read_file("/proc/meminfo")
    if meminfo:
        mem = {}
        for line in meminfo.splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]  # value in kB
                try:
                    mem[key] = int(val)
                except ValueError:
                    pass

        total_kb = mem.get("MemTotal", 0)
        avail_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
        used_kb = total_kb - avail_kb

        if total_kb:
            info["total_gb"] = round(total_kb / (1024 * 1024), 2)
            info["available_gb"] = round(avail_kb / (1024 * 1024), 2)
            info["used_gb"] = round(used_kb / (1024 * 1024), 2)
            info["percent_used"] = round((used_kb / total_kb) * 100, 1)

    return info


def get_disk_info() -> list[dict]:
    """Get disk usage for all mounted filesystems."""
    drives = []

    if HAS_PSUTIL:
        try:
            for part in psutil.disk_partitions(all=False):
                if part.fstype in ("tmpfs", "devtmpfs", "squashfs", "overlay"):
                    continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    drives.append({
                        "mount": part.mountpoint,
                        "device": part.device,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "used_gb": round(usage.used / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "percent_used": usage.percent,
                    })
                except PermissionError:
                    pass
            return drives
        except Exception:
            pass

    # Fallback to df
    raw = _run_cmd("df -BM --output=source,size,used,avail,pcent,target 2>/dev/null")
    if raw:
        lines = raw.splitlines()[1:]  # skip header
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                device = parts[0]
                if device.startswith("/dev/") or device.startswith("//"):
                    try:
                        total = int(parts[1].rstrip("M"))
                        used = int(parts[2].rstrip("M"))
                        avail = int(parts[3].rstrip("M"))
                        pct = int(parts[4].rstrip("%"))
                        mount = parts[5]
                        drives.append({
                            "mount": mount,
                            "device": device,
                            "total_gb": round(total / 1024, 2),
                            "used_gb": round(used / 1024, 2),
                            "free_gb": round(avail / 1024, 2),
                            "percent_used": pct,
                        })
                    except ValueError:
                        pass
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
                if iface["addresses"]:
                    interfaces.append(iface)
            return interfaces
        except Exception:
            pass

    # Fallback: parse ip addr
    raw = _run_cmd("ip -o addr show 2>/dev/null")
    if raw:
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                name = parts[1]
                family = parts[2]
                addr = parts[3].split("/")[0]
                # Find or create interface entry
                iface = next((i for i in interfaces if i["name"] == name), None)
                if not iface:
                    iface = {"name": name, "addresses": []}
                    interfaces.append(iface)
                if family == "inet":
                    iface["addresses"].append({"type": "IPv4", "address": addr})
                elif family == "inet6":
                    iface["addresses"].append({"type": "IPv6", "address": addr})

    # Filter out loopback
    interfaces = [i for i in interfaces if i["name"] != "lo"]
    return interfaces


def get_system_uptime() -> dict:
    """Get system uptime from /proc/uptime."""
    info = {"uptime_seconds": 0, "uptime_human": "unknown", "boot_time": None}

    uptime_str = _read_file("/proc/uptime")
    if uptime_str:
        try:
            uptime_secs = float(uptime_str.split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            mins = int((uptime_secs % 3600) // 60)
            info["uptime_seconds"] = int(uptime_secs)
            info["uptime_human"] = f"{days}d {hours}h {mins}m"
        except Exception:
            pass

    if HAS_PSUTIL:
        try:
            boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
            info["boot_time"] = boot.isoformat()
        except Exception:
            pass

    return info


def get_gpu_info() -> list[dict]:
    """Get GPU information."""
    gpus = []

    # Try nvidia-smi for NVIDIA GPUs
    nvidia = _run_cmd("nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null")
    if nvidia:
        for line in nvidia.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                gpus.append({
                    "name": parts[0],
                    "driver_version": parts[1],
                    "vram": parts[2],
                })

    # Fallback: lspci
    if not gpus:
        vga = _run_cmd("lspci 2>/dev/null | grep -i 'vga\\|3d\\|display'")
        if vga:
            for line in vga.splitlines():
                # Extract GPU name after the colon
                match = re.search(r":\s+(.+)", line)
                if match:
                    gpus.append({"name": match.group(1).strip()})

    return gpus


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


def get_load_average() -> dict:
    """Get system load average (Linux-specific)."""
    try:
        load = os.getloadavg()
        return {
            "1min": round(load[0], 2),
            "5min": round(load[1], 2),
            "15min": round(load[2], 2),
        }
    except Exception:
        return {}


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
    """Get Linux systemd services list."""
    services = []
    try:
        raw = _run_cmd("systemctl list-units --type=service --all --no-pager --no-legend", timeout=15)
        for line in raw.splitlines():
            parts = line.strip().split(None, 4)
            if len(parts) >= 4:
                name = parts[0].replace(".service", "")
                # LOAD ACTIVE SUB DESCRIPTION
                status = parts[2].lower()  # active/inactive
                sub_state = parts[3].lower()  # running/dead/exited
                desc = parts[4] if len(parts) > 4 else ""
                services.append({
                    "name": name,
                    "display_name": desc,
                    "status": sub_state,
                    "start_type": status,
                    "pid": None,
                })
        services.sort(key=lambda s: s.get("name", "").lower())
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

    # Fallback: ps
    try:
        raw = _run_cmd("ps aux --sort=-rss --no-headers | head -100", timeout=10)
        for line in raw.splitlines():
            parts = line.split(None, 10)
            if len(parts) >= 11:
                try:
                    processes.append({
                        "pid": int(parts[1]),
                        "name": parts[10][:50],
                        "cpu_percent": float(parts[2]),
                        "memory_mb": round(float(parts[5]) / 1024, 1) if parts[5].isdigit() else 0,
                        "username": parts[0],
                        "status": "running",
                    })
                except (ValueError, IndexError):
                    pass
        return {"processes": processes[:100], "total": len(processes)}
    except Exception as e:
        return {"error": str(e), "processes": []}


def _ts_software() -> dict:
    """Get installed packages."""
    software = []
    try:
        # Try dpkg first (Debian/Ubuntu)
        raw = _run_cmd("dpkg-query -W -f='${Package}\\t${Version}\\t${Installed-Size}\\n'", timeout=15)
        if raw:
            for line in raw.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    size = ""
                    if len(parts) >= 3 and parts[2].isdigit():
                        size = f"{round(int(parts[2]) / 1024, 1)} MB"
                    software.append({
                        "name": parts[0],
                        "version": parts[1],
                        "publisher": "",
                        "install_date": "",
                        "size": size,
                    })
        else:
            # Try rpm (RedHat/CentOS/Fedora)
            raw = _run_cmd("rpm -qa --queryformat '%{NAME}\\t%{VERSION}-%{RELEASE}\\t%{SIZE}\\n'", timeout=15)
            for line in raw.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    size = ""
                    if len(parts) >= 3 and parts[2].isdigit():
                        size = f"{round(int(parts[2]) / (1024*1024), 1)} MB"
                    software.append({
                        "name": parts[0],
                        "version": parts[1],
                        "publisher": "",
                        "install_date": "",
                        "size": size,
                    })
        software.sort(key=lambda s: s.get("name", "").lower())
        return {"software": software, "count": len(software)}
    except Exception as e:
        return {"error": str(e), "software": []}


def _ts_eventlog() -> dict:
    """Get recent syslog entries."""
    events = []
    try:
        # Try journalctl first
        raw = _run_cmd(
            "journalctl -p err..warning --no-pager -n 50 --output=json",
            timeout=15,
        )
        if raw:
            for line in raw.splitlines():
                try:
                    evt = json.loads(line)
                    ts = evt.get("__REALTIME_TIMESTAMP", "")
                    if ts:
                        try:
                            ts = datetime.fromtimestamp(int(ts) / 1000000).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                    priority = int(evt.get("PRIORITY", 6))
                    level = "Error" if priority <= 3 else "Warning" if priority <= 4 else "Info"
                    events.append({
                        "time": str(ts),
                        "level": level,
                        "source": evt.get("SYSLOG_IDENTIFIER", evt.get("_COMM", "")),
                        "message": evt.get("MESSAGE", "")[:200],
                    })
                except (json.JSONDecodeError, ValueError):
                    pass
        else:
            # Fallback: read /var/log/syslog or /var/log/messages
            for logfile in ["/var/log/syslog", "/var/log/messages"]:
                raw = _run_cmd(f"tail -50 {logfile}", timeout=10)
                if raw:
                    for line in raw.splitlines():
                        events.append({
                            "time": line[:15] if len(line) > 15 else "",
                            "level": "Warning" if "warn" in line.lower() else "Error" if "error" in line.lower() else "Info",
                            "source": "",
                            "message": line[:200],
                        })
                    break
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"error": str(e), "events": []}


def _ts_ls(path: str) -> dict:
    """List directory contents."""
    if not path:
        path = "/"
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
                        "is_dir": False,
                        "size": 0,
                        "modified": "",
                        "error": "access denied",
                    })
        except PermissionError:
            return {"error": f"Access denied: {path}", "path": path, "files": []}

        entries.sort(key=lambda e: (not e.get("is_dir", False), e.get("name", "").lower()))
        parent = os.path.dirname(path) if path != "/" else ""
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
        if size > 10 * 1024 * 1024:
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
        if pid <= 1:
            return {"error": "Cannot kill init/system process"}
        if HAS_PSUTIL:
            proc = psutil.Process(pid)
            name = proc.name()
            proc.kill()
            return {"success": True, "message": f"Killed process {name} (PID {pid})"}
        else:
            result = _run_cmd(f"kill -9 {pid}", timeout=10)
            return {"success": True, "message": result or f"Kill signal sent to PID {pid}"}
    except Exception as e:
        return {"error": str(e)}


def _ts_service(arg: str) -> dict:
    """Manage a systemd service: start, stop, restart."""
    parts = arg.split(":", 1)
    if len(parts) != 2:
        return {"error": "Usage: __ts:service:ACTION:SERVICE_NAME"}
    action, svc_name = parts[0], parts[1]

    if action not in ("start", "stop", "restart"):
        return {"error": f"Invalid action: {action}. Use start, stop, or restart."}

    try:
        result = _run_cmd(f"sudo systemctl {action} {svc_name}", timeout=30)
        return {"success": True, "action": action, "service": svc_name,
                "message": result or f"Service {svc_name} {action} command sent"}
    except Exception as e:
        return {"error": str(e)}


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
        "load_average": get_load_average(),
        "python_version": sys.version,
        "has_psutil": HAS_PSUTIL,
    }


# ── API Communication ──────────────────────────────────────────────────────

def get_or_create_monitor(api_url: str, api_key: str, hostname: str) -> str | None:
    """Register this agent as a heartbeat monitor, return monitor_id."""
    if not HAS_REQUESTS:
        print("ERROR: 'requests' package required. Install: pip3 install requests")
        return None

    headers = {"X-TS-API-Key": api_key}
    external_id = f"sys-agent-linux-{hostname}"

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

    try:
        payload = {
            "tenant_id": tenant_id,
            "name": f"🐧 {hostname} (Agent)",
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


def send_heartbeat(api_url: str, api_key: str, monitor_id: str, system_info: dict) -> tuple[bool, list]:
    """Send heartbeat with system info payload. Returns (success, messages)."""
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
            return True, messages
        return False, []
    except Exception as e:
        print(f"Heartbeat failed: {e}")
        return False, []


# ── Remote Command Execution ──────────────────────────────────────────────

BLOCKED_COMMANDS = [
    "rm -rf /", "mkfs", "dd if=", "shutdown", "reboot", "init 0",
    "halt", "poweroff", "> /dev/sda", ":(){ :|:", "chmod -R 777 /",
]


def _is_command_safe(cmd: str) -> bool:
    """Basic safety check — block destructive commands."""
    cmd_lower = cmd.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
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

            if not _is_command_safe(command):
                print(f"  ⛔ BLOCKED (unsafe): {command}")
                requests.post(
                    f"{api_url}/api/v1/commands/{cmd_id}/result",
                    json={"output": f"BLOCKED: Command '{command}' is not allowed for safety reasons.",
                          "exit_code": -1, "status": "failed"},
                    headers={"X-TS-API-Key": api_key}, timeout=10,
                )
                continue

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

            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=120, shell=True,
                )
                output = result.stdout
                if result.stderr:
                    output += "\n--- STDERR ---\n" + result.stderr
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
    with open(MONITOR_ID_FILE, "w") as f:
        f.write(mid)


# ── Service Install / Uninstall (systemd) ─────────────────────────────────

def _install_service(api_url: str, api_key: str, interval: int = 60):
    """Install as a systemd service."""
    _save_config(api_url, api_key, interval)

    python_exe = sys.executable
    agent_script = os.path.abspath(__file__)
    user = os.environ.get("USER", "root")

    unit = f"""[Unit]
Description=Tech Sentinel Monitor Agent (REGTeches)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
ExecStart={python_exe} {agent_script} --service
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
WorkingDirectory={os.path.dirname(agent_script)}

[Install]
WantedBy=multi-user.target
"""
    unit_path = f"/etc/systemd/system/{SERVICE_NAME}.service"

    print(f"\n{'='*60}")
    print("  Installing Tech Sentinel Agent as systemd service")
    print(f"{'='*60}")

    try:
        with open(unit_path, "w") as f:
            f.write(unit)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
        subprocess.run(["systemctl", "start", SERVICE_NAME], check=True)
        print(f"\n  ✅ Service installed and started!")
        print(f"  Check status: systemctl status {SERVICE_NAME}")
        print(f"  View logs:    journalctl -u {SERVICE_NAME} -f")
        print(f"  Uninstall:    python3 {os.path.basename(__file__)} --uninstall")
    except PermissionError:
        print(f"\n  ❌ Permission denied. Run with sudo:")
        print(f"  sudo python3 {os.path.basename(__file__)} --api-url {api_url} --api-key {api_key} --install")
    except Exception as e:
        print(f"\n  ❌ Install failed: {e}")


def _uninstall_service():
    print(f"\n{'='*60}")
    print("  Uninstalling Tech Sentinel Agent")
    print(f"{'='*60}")
    try:
        subprocess.run(["systemctl", "stop", SERVICE_NAME], capture_output=True)
        subprocess.run(["systemctl", "disable", SERVICE_NAME], capture_output=True)
        unit_path = f"/etc/systemd/system/{SERVICE_NAME}.service"
        if os.path.exists(unit_path):
            os.remove(unit_path)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        print(f"  ✅ Service removed.")
    except PermissionError:
        print("  ❌ Run with sudo.")
    except Exception as e:
        print(f"  ❌ {e}")


def _service_status():
    print(f"\n{'='*60}")
    print("  Tech Sentinel Agent — Status")
    print(f"{'='*60}")
    result = subprocess.run(
        ["systemctl", "status", SERVICE_NAME], capture_output=True, text=True)
    if result.returncode <= 3:
        for line in result.stdout.splitlines()[:8]:
            print(f"  {line}")
    else:
        print(f"  Service not installed.")
    cfg = _load_config()
    if cfg:
        print(f"\n  Config: api_url={cfg.get('api_url','?')}  interval={cfg.get('interval',60)}s")


# ── Main Entry Point ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Tech Sentinel Monitor — Linux System Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Created by Ronald Goodchild / REGTeches",
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
                        help="Install as systemd service (auto-start)")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the systemd service")
    parser.add_argument("--status", action="store_true",
                        help="Show service status")
    parser.add_argument("--service", action="store_true",
                        help="Run in service mode (headless)")
    args = parser.parse_args()

    if args.status:
        _service_status()
        return
    if args.uninstall:
        _uninstall_service()
        return

    print("=" * 60)
    print("  Tech Sentinel Monitor — Linux System Agent v" + APP_VERSION)
    print("  Created by Ronald Goodchild / REGTeches")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if args.print_only:
        info = collect_system_info()
        print(json.dumps(info, indent=2, default=str))
        return

    if not HAS_REQUESTS:
        print("\nERROR: 'requests' package is required.")
        print("Install it with:  pip3 install requests")
        sys.exit(1)

    # Load saved config, CLI args override
    saved_cfg = _load_config()
    api_url = args.api_url or saved_cfg.get("api_url", "")
    api_key = args.api_key or saved_cfg.get("api_key", "")
    interval = args.interval or saved_cfg.get("interval", 60)

    if not api_url or not api_key:
        print("\nERROR: --api-url and --api-key are required.")
        print(f"  Config: {CONFIG_FILE}")
        sys.exit(1)

    _save_config(api_url, api_key, interval)

    if args.install:
        _install_service(api_url, api_key, interval)
        return

    hostname = get_hostname()
    print(f"\nHostname: {hostname}")
    print(f"API:      {api_url}")
    print(f"Interval: {interval}s")

    monitor_id = _load_monitor_id()
    if not monitor_id:
        print("\nRegistering with Tech Sentinel...")
        monitor_id = get_or_create_monitor(api_url, api_key, hostname)
        if not monitor_id:
            sys.exit(1)
        _save_monitor_id(monitor_id)
    else:
        print(f"Monitor ID: {monitor_id} (cached)")

    print(f"\nStarting heartbeat loop (every {interval}s)...")
    if not args.service:
        print("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        cycle += 1
        try:
            info = collect_system_info()
            ok, messages = send_heartbeat(api_url, api_key, monitor_id, info)
            hb_status = "OK" if ok else "FAIL"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S" if args.service else "%H:%M:%S")
            ram = info["ram"]
            cpu = info["cpu"]
            load = info.get("load_average", {})
            print(
                f"[{ts}] #{cycle} {hb_status} | "
                f"CPU: {cpu.get('usage_percent', '?')}% | "
                f"RAM: {ram.get('percent_used', '?')}% "
                f"({ram.get('used_gb', '?')}/{ram.get('total_gb', '?')} GB) | "
                f"Load: {load.get('1min', '?')} | "
                f"Disks: {len(info['disks'])}"
            )

            for msg in messages:
                msg_type = msg.get("msg_type", "info")
                msg_text = msg.get("message", "")
                msg_id = msg.get("id", "")
                type_icons = {"info": "💬", "warning": "⚠️", "alert": "🚨"}
                print(f"  {type_icons.get(msg_type, '💬')} MESSAGE ({msg_type}): {msg_text}")

                if msg_type in ("alert", "warning"):
                    try:
                        _run_cmd(f'notify-send "Tech Sentinel {msg_type.upper()}" "{msg_text}"', timeout=5)
                    except Exception:
                        pass

                if msg_id:
                    try:
                        requests.post(
                            f"{api_url}/api/v1/messages/{msg_id}/delivered",
                            headers={"X-TS-API-Key": api_key}, timeout=5,
                        )
                    except Exception:
                        pass

            poll_and_execute_commands(api_url, api_key, monitor_id)

        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        if args.once:
            break

        elapsed = 0
        while elapsed < interval:
            try:
                time.sleep(min(5, interval - elapsed))
                elapsed += 5
                if elapsed < interval:
                    poll_and_execute_commands(api_url, api_key, monitor_id)
            except KeyboardInterrupt:
                print("\nStopped by user.")
                sys.exit(0)


if __name__ == "__main__":
    main()
