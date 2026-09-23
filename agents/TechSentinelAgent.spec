# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\ronal\\OneDrive\\Documents\\code\\TechSentinelMonitor\\agents\\windows_system_agent.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\ronal\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\certifi\\cacert.pem', 'certifi')],
    hiddenimports=['requests', 'requests.adapters', 'requests.auth', 'requests.cookies', 'requests.exceptions', 'urllib3', 'urllib3.util', 'urllib3.util.retry', 'urllib3.util.ssl_', 'urllib3.contrib', 'charset_normalizer', 'idna', 'certifi', 'psutil', 'psutil._pswindows', 'psutil._psutil_windows', 'winreg', 'ctypes', 'ctypes.wintypes', 'subprocess', 'socket', 'platform', 'logging', 'logging.handlers', 'ssl', '_ssl'],
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
    name='TechSentinelAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
