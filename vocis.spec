# -*- mode: python ; coding: utf-8 -*-
"""
Vocis（声幕）PyInstaller 打包配置。

用法:
    pyinstaller vocis.spec
    # 或直接:
    pyinstaller --onedir --windowed --name Vocis main.py
"""

import sys
from pathlib import Path

_root = Path(".").resolve()

a = Analysis(
    ["main.py"],
    pathex=[str(_root)],
    binaries=[],
    datas=[
        (".env.example", "."),
        ("assets", "assets"),
    ],
    hiddenimports=[
        "sounddevice",
        "numpy",
        "webrtcvad",
        "httpx",
        "dotenv",
        "pynput",
        "backend",
        "backend.config",
        "backend.capture",
        "backend.vad",
        "backend.asr",
        "backend.translator",
        "backend.pipeline",
        "gui",
        "gui.overlay",
        "gui.settings",
    ],
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
    name="Vocis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/vocis.ico",
)
