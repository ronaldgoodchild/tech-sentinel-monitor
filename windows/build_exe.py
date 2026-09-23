#!/usr/bin/env python3
"""
Tech Sentinel Monitor — PyInstaller EXE Builder
================================================
Builds a standalone Windows EXE with all dependencies bundled.

Usage:
    cd tech-sentinel-monitor
    pip install pyinstaller
    python windows/build_exe.py

Output:
    dist/TechSentinelMonitor.exe
"""

import os
import subprocess
import sys

# Fix Windows console encoding for emoji
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    os.chdir(project_dir)

    print("Tech Sentinel Monitor -- EXE Builder")
    print("=" * 50)

    # Check PyInstaller
    try:
        import PyInstaller
        print(f"   OK: PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("   Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Install deps
    req_file = os.path.join(script_dir, "requirements.txt")
    print("   Installing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", req_file])

    # Build the EXE
    print("\n>> Building EXE...")

    # Create the entry point script
    entry_point = os.path.join(project_dir, "_ts_entry.py")
    with open(entry_point, "w") as f:
        f.write("""import os, sys
# Ensure project root is in path
app_dir = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys, '_MEIPASS'):
    app_dir = sys._MEIPASS
sys.path.insert(0, app_dir)
from windows.launcher import main
main()
""")

    # Collect data files for the status page template
    template_src = os.path.join(project_dir, "status-page", "app", "templates")
    demo_src = os.path.join(project_dir, "demo")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "TechSentinelMonitor",
        "--icon", "NONE",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "jose",
        "--hidden-import", "jose.jwt",
        "--hidden-import", "pydantic",
        "--hidden-import", "pydantic_settings",
        "--hidden-import", "httpx",
        "--hidden-import", "multipart",
        "--hidden-import", "python_multipart",
        "--hidden-import", "windows.local_database",
        "--hidden-import", "windows.local_queue",
        "--hidden-import", "windows.local_api",
        "--hidden-import", "windows.local_probe_worker",
        "--hidden-import", "windows.local_status_page",
        "--hidden-import", "windows.local_alert_engine",
        "--hidden-import", "windows.local_branding",
        "--hidden-import", "windows.local_version_control",
        "--hidden-import", "windows.noc_importer",
        "--hidden-import", "windows.launcher",
        # Add data files
        "--add-data", f"{os.path.join('windows')}:windows",
        "--add-data", f"{demo_src}:demo",
        # Overwrite without prompting
        "--noconfirm",
        entry_point,
    ]

    print(f"   Running: {' '.join(cmd[-5:])}")
    result = subprocess.run(cmd, cwd=project_dir)

    # Clean up entry point
    if os.path.exists(entry_point):
        os.remove(entry_point)

    if result.returncode == 0:
        exe_path = os.path.join(project_dir, "dist", "TechSentinelMonitor.exe")
        print(f"\n>> Build successful!")
        print(f"   EXE: {exe_path}")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"   Size: {size_mb:.1f} MB")
        print(f"\n   Run it: dist\\TechSentinelMonitor.exe")
    else:
        print(f"\n>> Build FAILED with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
