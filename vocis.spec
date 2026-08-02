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
        ("models/faster-whisper-base", "models/faster-whisper-base"),
    ],
    hiddenimports=[
        "sounddevice",
        "numpy",
        "scipy",
        "scipy.signal",
        "onnxruntime",
        "httpx",
        "dotenv",
        "pynput",
        "comtypes",
        "faster_whisper",
        "ctranslate2",
        "backend",
        "backend.config",
        "backend.capture",
        "backend.vad",
        "backend.cache",
        "backend.asr",
        "backend.asr.base",
        "backend.asr.registry",
        "backend.asr.mimo",
        "backend.asr.whisper",
        "backend.asr.mock",
        "backend.translator",
        "backend.pipeline",
        "backend.wasapi_loopback",
        "backend.utils",
        "gui",
        "gui.overlay",
        "gui.subtitle_widget",
        "gui.tray",
        "gui.settings",
        "gui.setup_wizard",
        "gui.notification",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "tensorboard",
        "triton",
        "cv2",
        "opencv",
        "sklearn",
        "pandas",
        "matplotlib",
        "PIL",
        "IPython",
        "jupyter",
        "notebook",
    ],
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
