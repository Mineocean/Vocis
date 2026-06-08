"""
设置面板 —— 完整控件集合（课程设计要求）。

包含：QRadioButton、QCheckBox、QPushButton、QLabel、QLineEdit、
      QComboBox、QListWidget、QSpinBox、QGridLayout。
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QPushButton,
    QLabel,
    QGroupBox,
    QRadioButton,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QButtonGroup,
)
import sounddevice as sd

from backend.config import get_config

logger = logging.getLogger(__name__)


def _env_path() -> Path:
    return Path(__file__).parent.parent / ".env"


def _read_env() -> dict[str, str]:
    env = {}
    path = _env_path()
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _write_env(env: dict[str, str]):
    path = _env_path()
    if not path.exists():
        lines = [f"{k}={v}\n" for k, v in env.items()]
        path.write_text("".join(lines), encoding="utf-8")
        return
    existing = path.read_text(encoding="utf-8").splitlines()
    updated_keys = set()
    new_lines = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=")[0].strip()
            if k in env:
                new_lines.append(f"{k}={env[k]}")
                updated_keys.add(k)
                continue
        new_lines.append(line)
    for k, v in env.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}")
    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


class SettingsDialog(QDialog):
    """Vocis 设置对话框 — 完整控件演示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vocis 设置")
        self.setMinimumWidth(520)
        self.setMinimumHeight(460)
        self._env = _read_env()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # ═══ API 选项卡 ═══
        api_tab = QGroupBox()
        api_grid = QGridLayout(api_tab)
        api_grid.addWidget(QLabel("MiMo ASR Key:"), 0, 0)
        self._mimo_key = QLineEdit()
        self._mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._mimo_key.setPlaceholderText("输入 MiMo API Key")
        api_grid.addWidget(self._mimo_key, 0, 1)

        api_grid.addWidget(QLabel("DeepSeek Key:"), 1, 0)
        self._ds_key = QLineEdit()
        self._ds_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ds_key.setPlaceholderText("输入 DeepSeek API Key")
        api_grid.addWidget(self._ds_key, 1, 1)
        tabs.addTab(api_tab, "API")

        # ═══ 语言选项卡（QRadioButton）═══
        lang_tab = QGroupBox("识别语言")
        lang_grid = QGridLayout(lang_tab)

        self._lang_group = QButtonGroup(self)
        self._radio_auto = QRadioButton("自动检测 (auto)")
        self._radio_zh = QRadioButton("中文 (zh)")
        self._radio_en = QRadioButton("英文 (en)")
        self._radio_ja = QRadioButton("日语 (ja)")
        self._lang_group.addButton(self._radio_auto, 0)
        self._lang_group.addButton(self._radio_zh, 1)
        self._lang_group.addButton(self._radio_en, 2)
        self._lang_group.addButton(self._radio_ja, 3)

        lang_grid.addWidget(self._radio_auto, 0, 0)
        lang_grid.addWidget(self._radio_zh, 0, 1)
        lang_grid.addWidget(self._radio_en, 1, 0)
        lang_grid.addWidget(self._radio_ja, 1, 1)

        lang_grid.addWidget(QLabel("目标语言:"), 2, 0)
        self._target_lang = QLineEdit()
        self._target_lang.setPlaceholderText("中文 / English / 日本語")
        lang_grid.addWidget(self._target_lang, 2, 1)
        tabs.addTab(lang_tab, "语言")

        # ═══ 显示选项卡（QCheckBox + QGridLayout）═══
        display_tab = QGroupBox()
        display_grid = QGridLayout(display_tab)

        display_grid.addWidget(QLabel("字体大小:"), 0, 0)
        self._font_size = QSpinBox()
        self._font_size.setRange(10, 48)
        self._font_size.setValue(16)
        display_grid.addWidget(self._font_size, 0, 1)

        display_grid.addWidget(QLabel("字幕位置:"), 1, 0)
        self._position_combo = QComboBox()
        self._position_combo.addItems(["底部", "中部", "顶部"])
        display_grid.addWidget(self._position_combo, 1, 1)

        display_grid.addWidget(QLabel("显示屏幕:"), 2, 0)
        self._screen_combo = QComboBox()
        self._screen_combo.addItem("主屏幕")
        display_grid.addWidget(self._screen_combo, 2, 1)

        # 复选框组
        display_grid.addWidget(QLabel("显示选项:"), 3, 0)
        check_group = QVBoxLayout()
        self._check_stay = QCheckBox("字幕常驻显示（不自动消失）")
        self._check_topmost = QCheckBox("始终置顶")
        self._check_topmost.setChecked(True)
        self._check_clickthrough = QCheckBox("点击穿透")
        self._check_clickthrough.setChecked(True)
        self._check_autostart = QCheckBox("开机自启动")
        check_group.addWidget(self._check_stay)
        check_group.addWidget(self._check_topmost)
        check_group.addWidget(self._check_clickthrough)
        check_group.addWidget(self._check_autostart)
        display_grid.addLayout(check_group, 3, 1)
        tabs.addTab(display_tab, "显示")

        # ═══ 音频选项卡（QListWidget）═══
        audio_tab = QGroupBox()
        audio_grid = QGridLayout(audio_tab)

        audio_grid.addWidget(QLabel("音频设备列表:"), 0, 0, 1, 2)
        self._device_list = QListWidget()
        self._device_list.setMaximumHeight(160)
        self._refresh_devices()
        self._device_list.currentRowChanged.connect(self._on_device_selected)
        audio_grid.addWidget(self._device_list, 1, 0, 1, 2)

        self._device_info = QLabel("")
        self._device_info.setWordWrap(True)
        self._device_info.setStyleSheet("color: #888; font-size: 11px;")
        audio_grid.addWidget(self._device_info, 2, 0, 1, 2)

        audio_grid.addWidget(QLabel("识别模式:"), 3, 0)
        self._asr_backend = QComboBox()
        self._asr_backend.addItems(["mimo（云端）", "whisper（本地）", "mock（模拟）"])
        audio_grid.addWidget(self._asr_backend, 3, 1)

        audio_grid.addWidget(QLabel("Whisper 模型:"), 4, 0)
        self._whisper_model = QComboBox()
        self._whisper_model.addItems(["tiny（最快 ~40MB）", "base（~140MB）", "small（~460MB）"])
        audio_grid.addWidget(self._whisper_model, 4, 1)

        audio_grid.addWidget(QLabel("推理设备:"), 5, 0)
        self._whisper_device = QComboBox()
        self._whisper_device.addItems(["cuda（GPU）", "cpu（CPU）", "auto（自动）"])
        audio_grid.addWidget(self._whisper_device, 5, 1)

        self._gpu_info = QLabel("检测中...")
        self._gpu_info.setWordWrap(True)
        self._gpu_info.setStyleSheet("color: #888; font-size: 11px;")
        audio_grid.addWidget(self._gpu_info, 6, 0, 1, 2)
        # 延迟检测，避免阻塞窗口打开
        QTimer.singleShot(100, self._refresh_gpu_info)

        audio_grid.addWidget(QLabel("模型缓存:"), 7, 0)
        cache_label = QLabel(str(self._whisper_cache_dir()))
        cache_label.setStyleSheet("color: #666; font-size: 10px;")
        cache_label.setWordWrap(True)
        audio_grid.addWidget(cache_label, 7, 1)

        tabs.addTab(audio_tab, "音频")

        layout.addWidget(tabs)

        # ═══ 按钮 ═══
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._save)
        layout.addWidget(buttons)

    # ── 设备枚举 ──────────────────────────────────────

    def _refresh_gpu_info(self):
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                mem = torch.cuda.get_device_properties(0).total_memory // (1024**3)
                self._gpu_info.setText(f"检测到 GPU: {name} ({mem} GB)\nCUDA 版本: {torch.version.cuda}")
                self._whisper_device.setCurrentIndex(0)
            else:
                self._gpu_info.setText("CPU 模式运行中（t/c 每句约 1-2 秒）\n开启 GPU：pip install torch --index-url https://download.pytorch.org/whl/cu126")
                self._whisper_device.setCurrentIndex(1)
        except ImportError:
            self._gpu_info.setText("PyTorch 未安装。\n运行 .venv\\Scripts\\python.exe -m pip install torch")
            self._whisper_device.setCurrentIndex(1)

    def _whisper_cache_dir(self):
        from pathlib import Path
        p = Path.home() / ".cache" / "huggingface" / "hub"
        if p.exists():
            models = list(p.glob("models--*faster-whisper*"))
            if models:
                size = sum(f.stat().st_size for m in models for f in m.rglob("*") if f.is_file())
                return f"{p} ({size // (1024*1024)} MB)"
        return str(p)

    def _refresh_devices(self):
        self._device_list.clear()
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            wasapi_idx = None
            for i, api in enumerate(hostapis):
                if "wasapi" in api["name"].lower():
                    wasapi_idx = i
                    break

            for i, d in enumerate(devices):
                if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
                    item = QListWidgetItem(f"[{i}] {d['name']}")
                    item.setData(Qt.ItemDataRole.UserRole, i)
                    self._device_list.addItem(item)
        except Exception as e:
            logger.warning("枚举音频设备失败: %s", e)

    def _on_device_selected(self, row: int):
        item = self._device_list.item(row)
        if item is None:
            return
        dev_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            d = sd.query_devices(dev_id)
            info = (
                f"声道: {d['max_input_channels']} | "
                f"默认采样率: {int(d['default_samplerate'])} Hz | "
                f"API: {sd.query_hostapis()[d['hostapi']]['name']}"
            )
            self._device_info.setText(info)
        except Exception:
            self._device_info.setText("")

    # ── 加载 / 保存 ───────────────────────────────────

    def _load_values(self):
        cfg = get_config()

        self._mimo_key.setText(cfg.asr.api_key)
        self._ds_key.setText(cfg.translator.api_key)

        lang_map = {"auto": 0, "zh": 1, "en": 2, "ja": 3}
        idx = lang_map.get(cfg.asr.language, 0)
        self._lang_group.button(idx).setChecked(True)

        self._target_lang.setText(cfg.translator.target_language)

        font_size = int(self._env.get("FONT_SIZE", "16"))
        self._font_size.setValue(font_size)

        pos = self._env.get("SUBTITLE_POSITION", "bottom")
        pos_map = {"bottom": 0, "center": 1, "top": 2}
        self._position_combo.setCurrentIndex(pos_map.get(pos, 0))

        dur = int(self._env.get("SUBTITLE_DURATION", "5000"))
        self._check_stay.setChecked(dur == 0)

        backend_map = {"mimo": 0, "whisper": 1, "mock": 2}
        self._asr_backend.setCurrentIndex(backend_map.get(cfg.asr.backend.lower(), 0))

        # Whisper 设置
        model_map = {"tiny": 0, "base": 1, "small": 2}
        self._whisper_model.setCurrentIndex(model_map.get(cfg.asr.whisper_model, 0))
        dev_map = {"cuda": 0, "cpu": 1, "auto": 2}
        self._whisper_device.setCurrentIndex(dev_map.get(cfg.asr.whisper_device, 2))

    def _save(self):
        env = _read_env()

        env["MIMO_API_KEY"] = self._mimo_key.text().strip()
        env["DEEPSEEK_API_KEY"] = self._ds_key.text().strip()

        langs = ["auto", "zh", "en", "ja"]
        env["SOURCE_LANGUAGE"] = langs[self._lang_group.checkedId()]
        env["TARGET_LANGUAGE"] = self._target_lang.text().strip()

        env["FONT_SIZE"] = str(self._font_size.value())
        pos_vals = ["bottom", "center", "top"]
        env["SUBTITLE_POSITION"] = pos_vals[self._position_combo.currentIndex()]
        env["SUBTITLE_DURATION"] = "0" if self._check_stay.isChecked() else "5000"

        item = self._device_list.currentItem()
        if item:
            env["AUDIO_DEVICE"] = str(item.data(Qt.ItemDataRole.UserRole) or "auto")

        backends = ["mimo", "whisper", "mock"]
        env["ASR_BACKEND"] = backends[self._asr_backend.currentIndex()]

        models = ["tiny", "base", "small"]
        env["WHISPER_MODEL"] = models[self._whisper_model.currentIndex()]
        devices = ["cuda", "cpu", "auto"]
        env["WHISPER_DEVICE"] = devices[self._whisper_device.currentIndex()]

        _write_env(env)
        logger.info("设置已保存")

        import dotenv
        dotenv.load_dotenv(_env_path(), override=True)
        cfg = get_config()
        cfg.asr.api_key = env["MIMO_API_KEY"]
        cfg.asr.language = env["SOURCE_LANGUAGE"]
        cfg.translator.api_key = env["DEEPSEEK_API_KEY"]
        cfg.translator.target_language = env["TARGET_LANGUAGE"]

    def _save_and_close(self):
        self._save()
        self.accept()
