# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\ronal\\OneDrive\\Documents\\code\\TechSentinelMonitor\\tech-sentinel-monitor\\_ts_entry.py'],
    pathex=[],
    binaries=[],
    datas=[('windows', 'windows'), ('C:\\Users\\ronal\\OneDrive\\Documents\\code\\TechSentinelMonitor\\tech-sentinel-monitor\\demo', 'demo')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'jose', 'jose.jwt', 'pydantic', 'pydantic_settings', 'httpx', 'multipart', 'python_multipart', 'windows.local_database', 'windows.local_queue', 'windows.local_api', 'windows.local_probe_worker', 'windows.local_status_page', 'windows.local_alert_engine', 'windows.local_branding', 'windows.local_version_control', 'windows.noc_importer', 'windows.launcher'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TechSentinelMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)
