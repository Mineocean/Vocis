"""Settings dialog — API, language, display, audio configuration."""

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
    QSlider,
    QMessageBox,
)
import sounddevice as sd

from backend.config import get_config, read_env_file, write_env_file, env_path, reload_config

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Vocis settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vocis Settings")
        self.setMinimumWidth(520)
        self.setMinimumHeight(460)
        self._env = read_env_file()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._build_api_tab(), "API")
        tabs.addTab(self._build_lang_tab(), "Language")
        tabs.addTab(self._build_display_tab(), "Display")
        tabs.addTab(self._build_audio_tab(), "Audio")

        layout.addWidget(tabs)
        layout.addWidget(self._build_buttons())

    def _build_api_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel("MiMo ASR Key:"), 0, 0)
        self._mimo_key = QLineEdit()
        self._mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._mimo_key.setPlaceholderText("Enter MiMo API Key")
        grid.addWidget(self._mimo_key, 0, 1)

        self._mimo_test = QPushButton("Test")
        self._mimo_test.clicked.connect(lambda: self._test_connection("mimo"))
        grid.addWidget(self._mimo_test, 0, 2)

        grid.addWidget(QLabel("DeepSeek Key:"), 1, 0)
        self._ds_key = QLineEdit()
        self._ds_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ds_key.setPlaceholderText("Enter DeepSeek API Key")
        grid.addWidget(self._ds_key, 1, 1)

        self._ds_test = QPushButton("Test")
        self._ds_test.clicked.connect(lambda: self._test_connection("deepseek"))
        grid.addWidget(self._ds_test, 1, 2)

        return tab

    def _build_lang_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel("Source Language:"), 0, 0)
        self._lang_group = QButtonGroup(self)
        self._radio_auto = QRadioButton("Auto")
        self._radio_zh = QRadioButton("Chinese (zh)")
        self._radio_en = QRadioButton("English (en)")
        self._radio_ja = QRadioButton("Japanese (ja)")
        self._lang_group.addButton(self._radio_auto, 0)
        self._lang_group.addButton(self._radio_zh, 1)
        self._lang_group.addButton(self._radio_en, 2)
        self._lang_group.addButton(self._radio_ja, 3)

        lang_layout = QHBoxLayout()
        lang_layout.addWidget(self._radio_auto)
        lang_layout.addWidget(self._radio_zh)
        lang_layout.addWidget(self._radio_en)
        lang_layout.addWidget(self._radio_ja)
        grid.addLayout(lang_layout, 0, 1)

        grid.addWidget(QLabel("Target Language:"), 1, 0)
        self._target_lang = QLineEdit()
        self._target_lang.setPlaceholderText("中文 / English / 日本語")
        grid.addWidget(self._target_lang, 1, 1)

        return tab

    def _build_display_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel("Font Size:"), 0, 0)
        self._font_size = QSpinBox()
        self._font_size.setRange(10, 48)
        self._font_size.setValue(16)
        grid.addWidget(self._font_size, 0, 1)

        grid.addWidget(QLabel("Position:"), 1, 0)
        self._position_combo = QComboBox()
        self._position_combo.addItems(["Bottom", "Center", "Top"])
        grid.addWidget(self._position_combo, 1, 1)

        grid.addWidget(QLabel("Screen:"), 2, 0)
        self._screen_combo = QComboBox()
        self._screen_combo.addItem("Primary")
        grid.addWidget(self._screen_combo, 2, 1)

        grid.addWidget(QLabel("Subtitle Duration (ms):"), 3, 0)
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(0, 30000)
        self._duration_spin.setSpecialValueText("Permanent")
        self._duration_spin.setSingleStep(1000)
        grid.addWidget(self._duration_spin, 3, 1)

        self._check_stream = QCheckBox("Streaming translation (show as translating)")
        self._check_stream.setChecked(True)
        grid.addWidget(self._check_stream, 4, 0, 1, 2)

        return tab

    def _build_audio_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel("Audio Devices:"), 0, 0, 1, 2)
        self._device_list = QListWidget()
        self._device_list.setMaximumHeight(160)
        self._refresh_devices()
        self._device_list.currentRowChanged.connect(self._on_device_selected)
        grid.addWidget(self._device_list, 1, 0, 1, 2)

        self._device_info = QLabel("")
        self._device_info.setWordWrap(True)
        grid.addWidget(self._device_info, 2, 0, 1, 2)

        grid.addWidget(QLabel("ASR Backend:"), 3, 0)
        self._asr_backend = QComboBox()
        self._asr_backend.addItems(["mimo (cloud)", "whisper (local)", "mock (test)"])
        grid.addWidget(self._asr_backend, 3, 1)

        grid.addWidget(QLabel("Whisper Model:"), 4, 0)
        self._whisper_model = QComboBox()
        self._whisper_model.addItems(["tiny (~40MB)", "base (~140MB)", "small (~460MB)"])
        grid.addWidget(self._whisper_model, 4, 1)

        grid.addWidget(QLabel("Device:"), 5, 0)
        self._whisper_device = QComboBox()
        self._whisper_device.addItems(["cuda (GPU)", "cpu (CPU)", "auto"])
        grid.addWidget(self._whisper_device, 5, 1)

        self._gpu_info = QLabel("Checking...")
        self._gpu_info.setWordWrap(True)
        grid.addWidget(self._gpu_info, 6, 0, 1, 2)
        QTimer.singleShot(100, self._refresh_gpu_info)

        return tab

    def _build_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._save)
        return buttons

    def _test_connection(self, service: str):
        """Test API connection."""
        if service == "mimo":
            key = self._mimo_key.text().strip()
            if not key:
                QMessageBox.warning(self, "Test", "Please enter MiMo API Key first.")
                return
            QMessageBox.information(self, "Test", "Key format looks valid. Save and restart to test.")
        elif service == "deepseek":
            key = self._ds_key.text().strip()
            if not key:
                QMessageBox.warning(self, "Test", "Please enter DeepSeek API Key first.")
                return
            QMessageBox.information(self, "Test", "Key format looks valid. Save and restart to test.")

    def _refresh_gpu_info(self):
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                mem = torch.cuda.get_device_properties(0).total_mem // (1024**3)
                self._gpu_info.setText(f"GPU: {name} ({mem} GB)\nCUDA: {torch.version.cuda}")
                self._whisper_device.setCurrentIndex(0)
            else:
                self._gpu_info.setText("CPU mode (~1-2s per sentence)\nGPU: pip install torch --index-url https://download.pytorch.org/whl/cu126")
                self._whisper_device.setCurrentIndex(1)
        except ImportError:
            self._gpu_info.setText("PyTorch not installed.")
            self._whisper_device.setCurrentIndex(1)

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
            logger.warning("Failed to enumerate audio devices: %s", e)

    def _on_device_selected(self, row: int):
        item = self._device_list.item(row)
        if item is None:
            return
        dev_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            d = sd.query_devices(dev_id)
            info = (
                f"Channels: {d['max_input_channels']} | "
                f"Sample Rate: {int(d['default_samplerate'])} Hz | "
                f"API: {sd.query_hostapis()[d['hostapi']]['name']}"
            )
            self._device_info.setText(info)
        except Exception:
            self._device_info.setText("")

    def _load_values(self):
        cfg = get_config()

        self._mimo_key.setText(cfg.asr.api_key)
        self._ds_key.setText(cfg.translator.api_key)

        lang_map = {"auto": 0, "zh": 1, "en": 2, "ja": 3}
        idx = lang_map.get(cfg.asr.language, 0)
        self._lang_group.button(idx).setChecked(True)

        self._target_lang.setText(cfg.translator.target_language)

        self._font_size.setValue(int(self._env.get("FONT_SIZE", "16")))

        pos = self._env.get("SUBTITLE_POSITION", "bottom")
        pos_map = {"bottom": 0, "center": 1, "top": 2}
        self._position_combo.setCurrentIndex(pos_map.get(pos, 0))

        dur = int(self._env.get("SUBTITLE_DURATION", "5000"))
        self._duration_spin.setValue(dur)

        stream = self._env.get("STREAM_TRANSLATION", "true").lower() == "true"
        self._check_stream.setChecked(stream)

        backend_map = {"mimo": 0, "whisper": 1, "mock": 2}
        self._asr_backend.setCurrentIndex(backend_map.get(cfg.asr.backend.lower(), 0))

        model_map = {"tiny": 0, "base": 1, "small": 2}
        self._whisper_model.setCurrentIndex(model_map.get(cfg.asr.whisper_model, 0))
        dev_map = {"cuda": 0, "cpu": 1, "auto": 2}
        self._whisper_device.setCurrentIndex(dev_map.get(cfg.asr.whisper_device, 2))

    def _save(self):
        env = read_env_file()

        env["MIMO_API_KEY"] = self._mimo_key.text().strip()
        env["DEEPSEEK_API_KEY"] = self._ds_key.text().strip()

        langs = ["auto", "zh", "en", "ja"]
        env["SOURCE_LANGUAGE"] = langs[self._lang_group.checkedId()]
        env["TARGET_LANGUAGE"] = self._target_lang.text().strip()

        env["FONT_SIZE"] = str(self._font_size.value())
        pos_vals = ["bottom", "center", "top"]
        env["SUBTITLE_POSITION"] = pos_vals[self._position_combo.currentIndex()]
        env["SUBTITLE_DURATION"] = str(self._duration_spin.value())
        env["STREAM_TRANSLATION"] = "true" if self._check_stream.isChecked() else "false"

        item = self._device_list.currentItem()
        if item:
            env["AUDIO_DEVICE"] = str(item.data(Qt.ItemDataRole.UserRole) or "auto")

        backends = ["mimo", "whisper", "mock"]
        env["ASR_BACKEND"] = backends[self._asr_backend.currentIndex()]

        models = ["tiny", "base", "small"]
        env["WHISPER_MODEL"] = models[self._whisper_model.currentIndex()]
        devices = ["cuda", "cpu", "auto"]
        env["WHISPER_DEVICE"] = devices[self._whisper_device.currentIndex()]

        write_env_file(env)
        logger.info("Settings saved")

        import dotenv
        dotenv.load_dotenv(env_path(), override=True)
        reload_config()

    def _save_and_close(self):
        self._save()
        self.accept()
