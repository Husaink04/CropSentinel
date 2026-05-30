# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for CropSentinel Agent → standalone Windows executable.
#
# Build from the `installer/` directory:
#     pyinstaller agent.spec
#
# Produces:
#     installer/dist/cropsentinel-agent/cropsentinel-agent.exe  (+ bundled DLLs/pyd)
#
# See installer/build.ps1 for the full PyInstaller packaging pipeline.

import os

block_cipher = None

# Absolute path to the agent source directory (so the spec works regardless of
# which cwd PyInstaller is launched from).
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(SPEC), '..', 'agent'))
ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(SPEC), 'assets'))
APP_ICON = os.path.join(ASSETS_DIR, 'app.ico')

# ── Agent Analysis ────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(AGENT_DIR, 'agent.py')],
    pathex=[AGENT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Third-party runtime deps (PyInstaller usually finds these, but we
        # list them explicitly so a missed import fails fast on the dev
        # machine, not on the customer's PC).
        'bcrypt',
        'psutil',
        'PIL', 'PIL.Image', 'PIL.ImageDraw',
        'websocket', 'websocket._app',
        'pynput', 'pynput.keyboard', 'pynput.mouse',
        'watchdog', 'watchdog.observers', 'watchdog.events',
        'cryptography', 'cryptography.hazmat.primitives',
        'aiortc', 'aiortc.contrib.media',
        'av',
        'mss', 'mss.windows',
        'numpy',
        'pyautogui',
        'pyperclip',
        'sounddevice',
        'pywintypes',
        'pythoncom',
        'servicemanager',
        'win32api',
        'win32event',
        'win32service',
        'win32serviceutil',
        'win32timezone',
        # Local agent modules (same directory as agent.py). PyInstaller picks
        # these up through static analysis normally, but listing them here
        # guarantees they end up in the bundle even if an import is guarded.
        'dlp_engine',
        'dlp_destination',
        'dlp_fingerprint',
        'dlp_scoring',
        'file_tracker',
        'file_transfer',
        'input_tracker',
        'key_mapping',
        'network_tracker',
        'offline_queue',
        'print_tracker',
        'usb_tracker',
        'webrtc_agent',
        'windows_agent_service',
        'windows_watchdog_service',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavyweight packages we don't use — drop them to shrink the bundle.
        'tkinter',
        'matplotlib',
        'pytest',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cropsentinel-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX trips antivirus heuristics — leave off.
    console=False,      # No terminal window — agent is a silent background task.
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON if os.path.exists(APP_ICON) else None,
)

# ── Watchdog Analysis ─────────────────────────────────────────────────────────
# Minimal frozen exe — only needs stdlib + psutil.
w = Analysis(
    [os.path.join(AGENT_DIR, 'watchdog.py')],
    pathex=[AGENT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=['psutil'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'pytest', 'IPython', 'jupyter',
        'PIL', 'numpy', 'aiortc', 'pynput', 'watchdog', 'cryptography',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_w = PYZ(w.pure, w.zipped_data, cipher=block_cipher)

exe_w = EXE(
    pyz_w,
    w.scripts,
    [],
    exclude_binaries=True,
    name='cropsentinel-watchdog',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON if os.path.exists(APP_ICON) else None,
)

# ── Windows service hosts ───────────────────────────────────────────────────
s_agent = Analysis(
    [os.path.join(AGENT_DIR, 'windows_agent_service.py')],
    pathex=[AGENT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pywintypes',
        'pythoncom',
        'servicemanager',
        'win32api',
        'win32con',
        'win32event',
        'win32process',
        'win32profile',
        'win32service',
        'win32serviceutil',
        'win32security',
        'win32ts',
        'win32timezone',
        'agent',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_s_agent = PYZ(s_agent.pure, s_agent.zipped_data, cipher=block_cipher)

exe_s_agent = EXE(
    pyz_s_agent,
    s_agent.scripts,
    [],
    exclude_binaries=True,
    name='cropsentinel-agent-service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON if os.path.exists(APP_ICON) else None,
)

s_watchdog = Analysis(
    [os.path.join(AGENT_DIR, 'windows_watchdog_service.py')],
    pathex=[AGENT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pywintypes',
        'pythoncom',
        'servicemanager',
        'win32api',
        'win32event',
        'win32service',
        'win32serviceutil',
        'win32timezone',
        'watchdog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_s_watchdog = PYZ(s_watchdog.pure, s_watchdog.zipped_data, cipher=block_cipher)

exe_s_watchdog = EXE(
    pyz_s_watchdog,
    s_watchdog.scripts,
    [],
    exclude_binaries=True,
    name='cropsentinel-watchdog-service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON if os.path.exists(APP_ICON) else None,
)

# ── Unified COLLECT — both exes land in dist\cropsentinel-agent\ ─────────────
# The installer bootstrapper bundles both executables from this folder into one EXE.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    exe_w,
    w.binaries,
    w.zipfiles,
    w.datas,
    exe_s_agent,
    s_agent.binaries,
    s_agent.zipfiles,
    s_agent.datas,
    exe_s_watchdog,
    s_watchdog.binaries,
    s_watchdog.zipfiles,
    s_watchdog.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='cropsentinel-agent',
)
