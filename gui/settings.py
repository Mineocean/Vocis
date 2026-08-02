"""Settings dialog — API, language, display, audio configuration."""

import logging
import threading

import httpx
import sounddevice as sd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from backend.config import (
    env_path,
    get_config,
    read_env_file,
    reload_config,
    write_env_file,
)
from backend.utils import normalize_api_url
from gui.i18n import reload_language, tr

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Vocis settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))
        self.setMinimumWidth(520)
        self.setMinimumHeight(460)
        self._env = read_env_file()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()

        self._tabs.addTab(self._build_api_tab(), tr("tab_api"))
        self._tabs.addTab(self._build_lang_tab(), tr("tab_language"))
        self._tabs.addTab(self._build_display_tab(), tr("tab_display"))
        self._tabs.addTab(self._build_audio_tab(), tr("tab_audio"))

        layout.addWidget(self._tabs)
        layout.addWidget(self._build_buttons())

    def _build_api_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel(tr("mimo_key")), 0, 0)
        self._mimo_key = QLineEdit()
        self._mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._mimo_key.setPlaceholderText(tr("enter_mimo_key"))
        grid.addWidget(self._mimo_key, 0, 1)

        self._mimo_test = QPushButton(tr("test"))
        self._mimo_test.clicked.connect(lambda: self._test_connection("mimo"))
        grid.addWidget(self._mimo_test, 0, 2)

        grid.addWidget(QLabel(tr("deepseek_key")), 1, 0)
        self._ds_key = QLineEdit()
        self._ds_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ds_key.setPlaceholderText(tr("enter_ds_key"))
        grid.addWidget(self._ds_key, 1, 1)

        self._ds_test = QPushButton(tr("test"))
        self._ds_test.clicked.connect(lambda: self._test_connection("deepseek"))
        grid.addWidget(self._ds_test, 1, 2)

        grid.addWidget(QLabel(tr("ui_language")), 2, 0)
        self._ui_lang = QComboBox()
        self._ui_lang.addItems([tr("ui_lang_auto"), tr("ui_lang_zh"), tr("ui_lang_en")])
        grid.addWidget(self._ui_lang, 2, 1)

        return tab

    def _build_lang_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel(tr("source_language")), 0, 0)
        self._lang_group = QButtonGroup(self)
        self._radio_auto = QRadioButton(tr("auto"))
        self._radio_zh = QRadioButton(tr("chinese_zh"))
        self._radio_en = QRadioButton(tr("english_en"))
        self._radio_ja = QRadioButton(tr("japanese_ja"))
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

        grid.addWidget(QLabel(tr("target_language")), 1, 0)
        self._target_lang = QLineEdit()
        self._target_lang.setPlaceholderText(tr("target_lang_placeholder"))
        grid.addWidget(self._target_lang, 1, 1)

        return tab

    def _build_display_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel(tr("font_size")), 0, 0)
        self._font_size = QSpinBox()
        self._font_size.setRange(10, 48)
        self._font_size.setValue(16)
        grid.addWidget(self._font_size, 0, 1)

        grid.addWidget(QLabel(tr("position")), 1, 0)
        self._position_combo = QComboBox()
        self._position_combo.addItems(["Bottom", "Center", "Top"])
        grid.addWidget(self._position_combo, 1, 1)

        grid.addWidget(QLabel(tr("screen")), 2, 0)
        self._screen_combo = QComboBox()
        self._screen_combo.addItem(tr("screen_primary"))
        grid.addWidget(self._screen_combo, 2, 1)

        grid.addWidget(QLabel(tr("subtitle_duration")), 3, 0)
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(0, 30000)
        self._duration_spin.setSpecialValueText(tr("permanent"))
        self._duration_spin.setSingleStep(1000)
        grid.addWidget(self._duration_spin, 3, 1)

        self._check_permanent = QCheckBox(tr("permanent"))
        self._check_permanent.toggled.connect(self._on_permanent_toggled)
        grid.addWidget(self._check_permanent, 4, 0, 1, 2)

        self._check_stream = QCheckBox(tr("stream_translation"))
        self._check_stream.setChecked(True)
        grid.addWidget(self._check_stream, 5, 0, 1, 2)

        return tab

    def _on_permanent_toggled(self, checked: bool):
        """勾选"常驻"时锁定时长为 0（不自动隐藏），取消时恢复编辑。"""
        self._duration_spin.setEnabled(not checked)
        if checked:
            self._duration_spin.setValue(0)
        elif self._duration_spin.value() == 0:
            self._duration_spin.setValue(5000)

    def _build_audio_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)

        grid.addWidget(QLabel(tr("audio_devices")), 0, 0, 1, 2)
        self._device_list = QListWidget()
        self._device_list.setMaximumHeight(160)
        self._refresh_devices()
        self._device_list.currentRowChanged.connect(self._on_device_selected)
        grid.addWidget(self._device_list, 1, 0, 1, 2)

        self._device_info = QLabel("")
        self._device_info.setWordWrap(True)
        grid.addWidget(self._device_info, 2, 0, 1, 2)

        grid.addWidget(QLabel(tr("asr_backend")), 3, 0)
        self._asr_backend = QComboBox()
        self._asr_backend.addItems(["mimo (cloud)", "whisper (local)", "mock (test)"])
        grid.addWidget(self._asr_backend, 3, 1)

        grid.addWidget(QLabel(tr("whisper_model")), 4, 0)
        self._whisper_model = QComboBox()
        self._whisper_model.addItems(["tiny (~40MB)", "base (~140MB)", "small (~460MB)"])
        grid.addWidget(self._whisper_model, 4, 1)

        grid.addWidget(QLabel(tr("device")), 5, 0)
        self._whisper_device = QComboBox()
        self._whisper_device.addItems(["cuda (GPU)", "cpu (CPU)", "auto"])
        grid.addWidget(self._whisper_device, 5, 1)

        grid.addWidget(QLabel(tr("whisper_model_path")), 6, 0)
        self._whisper_model_path = QLineEdit()
        self._whisper_model_path.setPlaceholderText("models/faster-whisper-base")
        grid.addWidget(self._whisper_model_path, 6, 1)

        self._skip_translate_check = QCheckBox(tr("skip_translate_same_lang"))
        grid.addWidget(self._skip_translate_check, 7, 0, 1, 2)

        self._gpu_info = QLabel(tr("gpu_checking"))
        self._gpu_info.setWordWrap(True)
        grid.addWidget(self._gpu_info, 8, 0, 1, 2)
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
        """Test API connection with a real HTTP request (async, non-blocking)."""
        if service == "mimo":
            key = self._mimo_key.text().strip()
            if not key:
                QMessageBox.warning(self, tr("test_fail"), tr("test_enter_mimo_key"))
                return
            asr_cfg = get_config().asr
            url = normalize_api_url(asr_cfg.base_url) + "/chat/completions"
            headers = {"api-key": key, "Content-Type": "application/json"}
            # MiMo 是纯 ASR 服务，只接受 input_audio 内容，文本 "ping" 会返回 400。
            import base64
            from backend.asr.mimo import pcm_to_wav
            silence = b"\x00\x00" * 16000  # 1 秒 16bit 静音 PCM
            data_url = f"data:audio/wav;base64,{base64.b64encode(pcm_to_wav(silence)).decode('ascii')}"
            body: dict = {
                "model": asr_cfg.model,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "input_audio", "input_audio": {"data": data_url}}
                    ]}
                ],
                "max_tokens": 1,
            }
        elif service == "deepseek":
            key = self._ds_key.text().strip()
            if not key:
                QMessageBox.warning(self, tr("test_fail"), tr("test_enter_ds_key"))
                return
            tr_cfg = get_config().translator
            url = normalize_api_url(tr_cfg.base_url) + "/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            body = {
                "model": tr_cfg.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            }
        else:
            return

        button = self._mimo_test if service == "mimo" else self._ds_test
        button.setEnabled(False)
        button.setText(tr("test_progress"))

        def _run():
            ok, detail = False, ""
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    ok = True
                    detail = tr("test_connected")
                elif resp.status_code in (401, 403):
                    detail = tr("test_auth_failed", code=resp.status_code)
                else:
                    detail = tr("test_http_error", code=resp.status_code, text=resp.text[:200])
            except httpx.HTTPError as e:
                detail = tr("test_request_failed", error=e)
            QTimer.singleShot(0, lambda: self._on_test_done(button, ok, detail))

        threading.Thread(target=_run, daemon=True).start()

    def _on_test_done(self, button, ok: bool, detail: str):
        button.setEnabled(True)
        button.setText(tr("test"))
        if ok:
            QMessageBox.information(self, tr("test_ok"), detail)
        else:
            QMessageBox.warning(self, tr("test_fail"), detail)

    def _refresh_gpu_info(self):
        cfg = get_config().asr
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                mem = torch.cuda.get_device_properties(0).total_mem // (1024**3)
                self._gpu_info.setText(tr("gpu_cuda", name=name, mem=mem, cuda=torch.version.cuda))
                if cfg.whisper_device == "auto":
                    self._whisper_device.setCurrentIndex(0)
            else:
                self._gpu_info.setText(tr("gpu_cpu_mode"))
                if cfg.whisper_device == "auto":
                    self._whisper_device.setCurrentIndex(1)
        except ImportError:
            self._gpu_info.setText(tr("gpu_no_torch"))
            if cfg.whisper_device == "auto":
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
            info = tr(
                "channels_info",
                channels=d["max_input_channels"],
                rate=int(d["default_samplerate"]),
                api=sd.query_hostapis()[d["hostapi"]]["name"],
            )
            self._device_info.setText(info)
        except Exception:
            self._device_info.setText("")

    def _load_values(self):
        cfg = get_config()

        self._mimo_key.setText(cfg.asr.api_key)
        self._ds_key.setText(cfg.translator.api_key)

        ui_lang = self._env.get("UI_LANGUAGE", "").strip().lower()
        ui_map = {"": 0, "zh": 1, "en": 2}
        self._ui_lang.setCurrentIndex(ui_map.get(ui_lang, 0))

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
        self._check_permanent.setChecked(dur == 0)
        self._duration_spin.setEnabled(dur != 0)

        stream = self._env.get("STREAM_TRANSLATION", "true").lower() == "true"
        self._check_stream.setChecked(stream)

        backend_map = {"mimo": 0, "whisper": 1, "mock": 2}
        self._asr_backend.setCurrentIndex(backend_map.get(cfg.asr.backend.lower(), 0))

        model_map = {"tiny": 0, "base": 1, "small": 2}
        self._whisper_model.setCurrentIndex(model_map.get(cfg.asr.whisper_model, 0))
        dev_map = {"cuda": 0, "cpu": 1, "auto": 2}
        self._whisper_device.setCurrentIndex(dev_map.get(cfg.asr.whisper_device, 2))

        self._whisper_model_path.setText(cfg.asr.whisper_model_path)
        self._skip_translate_check.setChecked(cfg.asr.skip_translate_when_same_lang)

    def _save(self):
        env = read_env_file()

        env["MIMO_API_KEY"] = self._mimo_key.text().strip()
        env["DEEPSEEK_API_KEY"] = self._ds_key.text().strip()

        ui_vals = ["", "zh", "en"]
        env["UI_LANGUAGE"] = ui_vals[self._ui_lang.currentIndex()]

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
            dev_id = item.data(Qt.ItemDataRole.UserRole)
            env["AUDIO_DEVICE"] = str(dev_id) if dev_id is not None else "auto"

        backends = ["mimo", "whisper", "mock"]
        env["ASR_BACKEND"] = backends[self._asr_backend.currentIndex()]

        models = ["tiny", "base", "small"]
        env["WHISPER_MODEL"] = models[self._whisper_model.currentIndex()]
        devices = ["cuda", "cpu", "auto"]
        env["WHISPER_DEVICE"] = devices[self._whisper_device.currentIndex()]
        env["WHISPER_MODEL_PATH"] = self._whisper_model_path.text().strip() or "models/faster-whisper-base"
        env["SKIP_TRANSLATE_SAME_LANG"] = "true" if self._skip_translate_check.isChecked() else "false"

        write_env_file(env)
        logger.info("Settings saved")

        import dotenv
        dotenv.load_dotenv(env_path(), override=True)
        reload_config()
        reload_language()

    def _save_and_close(self):
        self._save()
        self.accept()
