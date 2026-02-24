# -*- mode: python ; coding: utf-8 -*-

import os

PY_HOME = r"C:/Users/Ionut.Emilian/AppData/Local/Programs/Python/Python313"


a = Analysis(
    ['launch_dashboard.py'],
    pathex=[],
    binaries=[
        (f"{PY_HOME}/python313.dll", "."),
        (f"{PY_HOME}/vcruntime140.dll", "."),
        (f"{PY_HOME}/vcruntime140_1.dll", "."),
    ],
    datas=[('C:/Users/Ionut.Emilian/AppData/Local/Programs/Python/Python313/Lib/site-packages/customtkinter', 'customtkinter'), ('C:/Users/Ionut.Emilian/AppData/Local/Programs/Python/Python313/Lib/site-packages/darkdetect', 'darkdetect')],
    hiddenimports=['customtkinter', 'darkdetect', 'samsung_mdc', 'samsungtvws', 'websocket', 'requests', 'PIL', 'PIL._tkinter_finder'],
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
    name='SamsungMDCDashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=os.path.join(os.getenv('LOCALAPPDATA', '.'), 'SamsungPyRuntime'),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
