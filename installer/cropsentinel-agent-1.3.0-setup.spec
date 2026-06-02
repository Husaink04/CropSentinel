# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\husai\\OneDrive\\Desktop\\CropSentinel\\installer\\bootstrapper.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\husai\\OneDrive\\Desktop\\CropSentinel\\agent\\native\\publish\\win-x64', 'cropsentinel-agent'), ('C:\\Users\\husai\\OneDrive\\Desktop\\CropSentinel\\installer\\config.env.example', '.'), ('C:\\Users\\husai\\OneDrive\\Desktop\\CropSentinel\\installer\\assets\\app.ico', '.')],
    hiddenimports=[],
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
    name='cropsentinel-agent-1.3.0-setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['C:\\Users\\husai\\OneDrive\\Desktop\\CropSentinel\\installer\\assets\\app.ico'],
)
