#!/usr/bin/env python3
"""
Tech Sentinel Monitor — Windows Run Script
==========================================
Quick-start script: installs deps and launches the GUI.

Usage:
    cd tech-sentinel-monitor
    python windows/run.py
"""

import os
import subprocess
import sys


def main():
    # Ensure we're in the right directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    os.chdir(project_dir)

    # Add project root to path
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    # Check / install dependencies
    print("\U0001f6e1\ufe0f Tech Sentinel Monitor — Windows Launcher")
    print("=" * 50)

    req_file = os.path.join(script_dir, "requirements.txt")
    print("\n\U0001f4e6 Checking dependencies...")

    missing = []
    deps = ["fastapi", "uvicorn", "httpx", "jose", "pydantic", "pydantic_settings"]
    for dep in deps:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)

    if missing:
        print(f"   Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-q", "-r", req_file
        ])
        print("   \u2705 Dependencies installed")
    else:
        print("   \u2705 All dependencies present")

    # Launch the GUI
    print("\n\U0001f680 Launching Tech Sentinel Monitor...\n")
    from windows.launcher import main as launch
    launch()


if __name__ == "__main__":
    main()
