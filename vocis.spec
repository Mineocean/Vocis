# -*- mode: python ; coding: utf-8 -*-
"""
Vocis（声幕）PyInstaller 打包配置。

用法:
    pyinstaller vocis.spec
    # 或直接:
    pyinstaller --onedir --windowed --name Vocis main.py
"""

import os
import sys
from pathlib import Path

_root = Path(".").resolve()

if sys.platform == "win32":
    from PyInstaller.utils.win32.winutils import get_system_path

    # 优先解析 Windows 系统 DLL，避免 PATH 中其他软件的同名 DLL 被打包。
    os.environ["PATH"] = os.pathsep.join([*get_system_path(), os.environ.get("PATH", "")])

# opencc 数据文件（config/*.json + dictionary/*.json），打包后随 opencc 包路径展开
_opencc_base = _root / ".venv" / "Lib" / "site-packages" / "opencc"
_opencc_datas = []
if _opencc_base.exists():
    _opencc_datas += [
        (str(_opencc_base / "config"), "opencc/config"),
        (str(_opencc_base / "dictionary"), "opencc/dictionary"),
    ]

a = Analysis(
    ["main.py"],
    pathex=[str(_root)],
    binaries=[],
    datas=[
        (".env.example", "."),
        ("assets", "assets"),
        ("models/faster-whisper-base", "models/faster-whisper-base"),
        ("models/sherpa-streaming-zh-14M", "models/sherpa-streaming-zh-14M"),
        *_opencc_datas,
    ],
    hiddenimports=[
        "sounddevice",
        "numpy",
        "scipy",
        "scipy.signal",
        "scipy.fftpack",
        "scipy.special",
        "onnxruntime",
        "httpx",
        "dotenv",
        "pynput",
        "comtypes",
        "faster_whisper",
        "ctranslate2",
        "sherpa_onnx",
        "backend",
        "backend.config",
        "backend.capture",
        "backend.vad",
        "backend.cache",
        "backend.asr",
        "backend.asr.base",
        "backend.asr.registry",
        "backend.asr.audio",
        "backend.asr.mimo",
        "backend.asr.whisper",
        "backend.asr.sherpa",
        "backend.asr.mock",
        "backend.asr.openai_compat",
        "backend.providers",
        "backend.providers.presets",
        "backend.diarization",
        "backend.diarization.base",
        "backend.diarization.clustering",
        "backend.diarization.cluster",
        "backend.diarization.sherpa_embedding",
        "backend.translator",
        "backend.pipeline",
        "backend.wasapi_loopback",
        "backend.utils",
        "gui",
        "gui.overlay",
        "gui.theme",
        "gui.widgets",
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
