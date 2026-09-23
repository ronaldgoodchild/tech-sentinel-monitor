#!/usr/bin/env python3
"""
Tech Sentinel Monitor — Agent EXE Builder
==========================================
Builds a single standalone TechSentinelAgent.exe that runs on any
Windows 10/11 PC with no Python, no pip, no dependencies needed.

Usage (run from the agents/ folder):
    python build_agent.py

Output:
    agents/dist/TechSentinelAgent.exe   ← ship this one file

By Ronald Goodchild / REGTeches
"""

import os
import subprocess
import sys


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    agent_script = os.path.join(script_dir, "windows_system_agent.py")

    # ── Fix Windows console encoding for emoji/unicode ────────────────────
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("  Tech Sentinel Agent — EXE Builder")
    print("  REGTeches / Ronald Goodchild")
    print("=" * 60)

    # ── Verify source exists ──────────────────────────────────────────────
    if not os.path.exists(agent_script):
        print(f"\n  ERROR: Cannot find agent script at:\n  {agent_script}")
        sys.exit(1)
    print(f"\n  Source : {agent_script}")

    # ── Ensure dependencies are installed ────────────────────────────────
    print("\n  Checking / installing dependencies...")
    deps = ["pyinstaller", "requests", "psutil"]
    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"    OK  {dep}")
        except ImportError:
            print(f"    Installing {dep}...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", dep]
            )
            print(f"    OK  {dep} (installed)")

    # ── Locate certifi CA bundle for SSL (requests depends on it) ────────
    cert_datas = []
    try:
        import certifi
        ca_bundle = certifi.where()
        if os.path.exists(ca_bundle):
            cert_datas = [f"{ca_bundle}:certifi"]
            print(f"    OK  certifi CA bundle: {ca_bundle}")
    except ImportError:
        print("    WARN  certifi not found — HTTPS may fail on target PC")

    # ── Build command ─────────────────────────────────────────────────────
    out_dir = os.path.join(script_dir, "dist")
    work_dir = os.path.join(script_dir, "build")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",               # Single EXE — no folder mess
        "--console",               # Keep console window (agent logs to it)
        "--name", "TechSentinelAgent",
        "--distpath", out_dir,
        "--workpath", work_dir,
        "--specpath", script_dir,
        "--noconfirm",             # Overwrite previous build without prompting

        # ── Hidden imports PyInstaller might miss ──────────────────────
        # requests + urllib3 + SSL stack
        "--hidden-import", "requests",
        "--hidden-import", "requests.adapters",
        "--hidden-import", "requests.auth",
        "--hidden-import", "requests.cookies",
        "--hidden-import", "requests.exceptions",
        "--hidden-import", "urllib3",
        "--hidden-import", "urllib3.util",
        "--hidden-import", "urllib3.util.retry",
        "--hidden-import", "urllib3.util.ssl_",
        "--hidden-import", "urllib3.contrib",
        "--hidden-import", "charset_normalizer",
        "--hidden-import", "idna",
        "--hidden-import", "certifi",

        # psutil (Windows-specific sub-modules)
        "--hidden-import", "psutil",
        "--hidden-import", "psutil._pswindows",
        "--hidden-import", "psutil._psutil_windows",

        # Windows standard library modules
        "--hidden-import", "winreg",
        "--hidden-import", "ctypes",
        "--hidden-import", "ctypes.wintypes",
        "--hidden-import", "subprocess",
        "--hidden-import", "socket",
        "--hidden-import", "platform",
        "--hidden-import", "logging",
        "--hidden-import", "logging.handlers",

        # Encryption / SSL (needed by requests over HTTPS)
        "--hidden-import", "ssl",
        "--hidden-import", "_ssl",
    ]

    # Add certifi CA bundle as bundled data
    for data_entry in cert_datas:
        cmd += ["--add-data", data_entry]

    # The agent script itself
    cmd.append(agent_script)

    # ── Run PyInstaller ───────────────────────────────────────────────────
    print(f"\n  Building EXE (this takes ~30-60 seconds)...\n")
    result = subprocess.run(cmd, cwd=script_dir)

    # ── Report result ─────────────────────────────────────────────────────
    exe_path = os.path.join(out_dir, "TechSentinelAgent.exe")
    if result.returncode == 0 and os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL")
        print("=" * 60)
        print(f"\n  EXE   : {exe_path}")
        print(f"  Size  : {size_mb:.1f} MB")
        print(f"\n  DEPLOY — copy TechSentinelAgent.exe to target PC, then:")
        print(f"\n    (Run Command Prompt as Administrator)")
        print(f"    TechSentinelAgent.exe --api-url http://192.168.1.121:8000 \\")
        print(f"                          --api-key YOUR_API_KEY --install")
        print(f"\n    TechSentinelAgent.exe --status     <- check it's running")
        print(f"\n  No Python needed on the target PC.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("  BUILD FAILED")
        print("=" * 60)
        print(f"\n  Exit code : {result.returncode}")
        print(f"  Check the output above for errors.")
        print(f"  Build logs : {work_dir}")
        sys.exit(1)


if __name__ == "__main__":
    main()
