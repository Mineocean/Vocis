"""Settings dialog — 翻译 / 语音识别 / 说话人 / 显示 / 音频 配置。"""

import logging
import threading
from pathlib import Path

import httpx
import sounddevice as sd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from backend.asr.audio import pcm_to_wav
from backend.config import (
    app_dir,
    env_path,
    get_config,
    read_env_file,
    reload_config,
    write_env_file,
)
from backend.providers.presets import ASR_PRESETS, LOCAL_ASR_BACKENDS, TRANSLATION_PRESETS
from backend.utils import normalize_api_url
from gui.i18n import current_language, reload_language, tr
from gui.widgets import (
    ThemedCheckBox,
    ThemedComboBox,
    ThemedDoubleSpinBox,
    ThemedRadioButton,
    ThemedSpinBox,
)

logger = logging.getLogger(__name__)

SOURCE_LANGS = ["auto", "zh", "en", "ja"]
POSITIONS = ["bottom", "center", "top"]
WHISPER_MODELS = ["tiny", "base", "small", "medium"]
WHISPER_DEVICES = ["cuda", "cpu", "auto"]
LOCAL_BACKENDS = ["whisper", "sherpa", "mock"]


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("formLabel")
    return lbl


def _hint(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


def _preset_name(preset: dict, fallback: str = "") -> str:
    key = "name_zh" if current_language() == "zh" else "name"
    return preset.get(key) or preset.get("name") or fallback


def _http_result(resp: httpx.Response) -> tuple[bool, str]:
    if resp.status_code == 200:
        return True, tr("test_connected")
    if resp.status_code in (401, 403):
        return False, tr("test_auth_failed", code=resp.status_code)
    return False, tr("test_http_error", code=resp.status_code, text=resp.text[:200])


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else app_dir() / p


class SettingsDialog(QDialog):
    """Vocis settings dialog."""

    def __init__(self, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))
        self.resize(760, 680)
        self.setMinimumSize(700, 600)
        self._env = read_env_file()
        self._build_ui()
        self._load_values()
        if 0 <= initial_tab < self._tabs.count():
            self._tabs.setCurrentIndex(initial_tab)
        self._connect_test_reset()

    def showEvent(self, event):
        # 只在对话框可见时监听焦点；避免应用退出时仍持有跨对象信号连接
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._ensure_focus_visible)
        super().showEvent(event)

    def hideEvent(self, event):
        app = QApplication.instance()
        if isinstance(app, QApplication):
            try:
                app.focusChanged.disconnect(self._ensure_focus_visible)
            except (RuntimeError, TypeError):
                pass
        super().hideEvent(event)

    def _ensure_focus_visible(self, _old, new):
        """键盘 Tab / setFocus 时让 QScrollArea 跟随滚动，避免在视口外盲输。"""
        if new is None:
            return
        for i in range(self._tabs.count()):
            area = self._tabs.widget(i)
            if isinstance(area, QScrollArea) and area.isAncestorOf(new):
                area.ensureWidgetVisible(new, 0, 28)
                return

    def _connect_test_reset(self):
        """改动输入后清掉上一次测试结果的红色/绿色残留。"""
        for widget in (self._tr_key, self._tr_base):
            widget.textChanged.connect(self._reset_test_state)
        self._tr_model.currentTextChanged.connect(self._reset_test_state)
        for widget in (self._asr_key, self._asr_base):
            widget.textChanged.connect(self._reset_test_state)
        self._asr_model.currentTextChanged.connect(self._reset_test_state)

    def _reset_test_state(self, *_args):
        for label in (self._tr_test_status, self._asr_test_status):
            label.setText(tr("not_tested"))
            label.setStyleSheet("")

    # ── 构建 ──────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel(tr("settings_title"))
        title.setObjectName("dialogTitle")
        head.addWidget(title)
        head.addWidget(_hint(tr("settings_subtitle")))
        outer.addLayout(head)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._scroll(self._build_translate_tab()), tr("tab_translator"))
        self._tabs.addTab(self._scroll(self._build_asr_tab()), tr("tab_asr"))
        self._tabs.addTab(self._scroll(self._build_diarization_tab()), tr("tab_diarization"))
        self._tabs.addTab(self._scroll(self._build_display_tab()), tr("tab_display"))
        self._tabs.addTab(self._scroll(self._build_audio_tab()), tr("tab_audio"))
        outer.addWidget(self._tabs, 1)

        outer.addWidget(self._build_buttons())

    @staticmethod
    def _tab_page() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("scrollContent")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        return page, lay

    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(page)
        return area

    @staticmethod
    def _form(group: QGroupBox) -> QFormLayout:
        form = QFormLayout(group)
        form.setContentsMargins(14, 8, 14, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return form

    def _build_translate_tab(self) -> QWidget:
        page, lay = self._tab_page()

        group = QGroupBox(tr("provider"))
        form = self._form(group)

        self._tr_provider = ThemedComboBox()
        for key, preset in TRANSLATION_PRESETS.items():
            self._tr_provider.addItem(_preset_name(preset, key), key)
        self._tr_provider.currentIndexChanged.connect(self._on_translation_provider_changed)
        form.addRow(_label(tr("provider")), self._tr_provider)

        self._tr_key = QLineEdit()
        self._tr_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._tr_key.setPlaceholderText(tr("enter_key"))
        form.addRow(_label(tr("api_key")), self._tr_key)

        self._tr_base = QLineEdit()
        self._tr_base.setPlaceholderText(tr("enter_base_url"))
        form.addRow(_label(tr("base_url")), self._tr_base)

        self._tr_model = ThemedComboBox()
        self._tr_model.setEditable(True)
        self._tr_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._tr_model.lineEdit().setPlaceholderText(tr("enter_model"))
        form.addRow(_label(tr("model")), self._tr_model)

        lay.addWidget(group)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self._tr_test_btn = QPushButton(tr("test_connection"))
        self._tr_test_btn.setAutoDefault(False)
        self._tr_test_btn.clicked.connect(self._test_translator)
        self._tr_test_status = _hint(tr("not_tested"))
        test_row.addWidget(self._tr_test_btn)
        test_row.addWidget(self._tr_test_status, 1)
        lay.addLayout(test_row)

        self._tr_hint = _hint()
        lay.addWidget(self._tr_hint)

        lang_group = QGroupBox(tr("tab_language"))
        lang_form = self._form(lang_group)
        self._source_lang = ThemedComboBox()
        for value in SOURCE_LANGS:
            self._source_lang.addItem(self._lang_label(value), value)
        lang_form.addRow(_label(tr("source_language")), self._source_lang)
        self._target_lang = QLineEdit()
        self._target_lang.setPlaceholderText(tr("target_lang_placeholder"))
        lang_form.addRow(_label(tr("target_language")), self._target_lang)
        lay.addWidget(lang_group)

        adv_group = QGroupBox(tr("advanced"))
        adv_form = self._form(adv_group)
        self._tr_temp = ThemedDoubleSpinBox()
        self._tr_temp.setRange(0.0, 2.0)
        self._tr_temp.setSingleStep(0.1)
        self._tr_temp.setDecimals(2)
        adv_form.addRow(_label(tr("temperature")), self._tr_temp)
        self._tr_max_tokens = ThemedSpinBox()
        self._tr_max_tokens.setRange(16, 8192)
        self._tr_max_tokens.setSingleStep(64)
        adv_form.addRow(_label(tr("max_tokens")), self._tr_max_tokens)
        lay.addWidget(adv_group)

        lay.addStretch(1)
        return page

    def _build_asr_tab(self) -> QWidget:
        page, lay = self._tab_page()

        mode_group = QGroupBox(tr("asr_mode"))
        mode_lay = QHBoxLayout(mode_group)
        mode_lay.setContentsMargins(14, 8, 14, 8)
        mode_lay.setSpacing(20)
        self._asr_cloud_radio = ThemedRadioButton(tr("asr_mode_cloud"))
        self._asr_local_radio = ThemedRadioButton(tr("asr_mode_local"))
        self._asr_cloud_radio.setChecked(True)
        self._asr_cloud_radio.toggled.connect(self._on_asr_mode_changed)
        mode_lay.addWidget(self._asr_cloud_radio)
        mode_lay.addWidget(self._asr_local_radio)
        mode_lay.addStretch(1)
        lay.addWidget(mode_group)

        self._asr_stack = QStackedWidget()
        self._asr_stack.addWidget(self._build_asr_cloud_page())
        self._asr_stack.addWidget(self._build_asr_local_page())
        lay.addWidget(self._asr_stack)

        self._skip_translate = ThemedCheckBox(tr("skip_translate_same_lang"))
        self._skip_translate.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay.addWidget(self._skip_translate)
        lay.addStretch(1)
        return page

    def _build_asr_cloud_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        group = QGroupBox(tr("asr_cloud"))
        form = self._form(group)

        self._asr_provider = ThemedComboBox()
        for key, preset in ASR_PRESETS.items():
            self._asr_provider.addItem(_preset_name(preset, key), key)
        self._asr_provider.currentIndexChanged.connect(self._on_asr_provider_changed)
        form.addRow(_label(tr("provider")), self._asr_provider)

        self._asr_key = QLineEdit()
        self._asr_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._asr_key.setPlaceholderText(tr("enter_key"))
        form.addRow(_label(tr("api_key")), self._asr_key)

        self._asr_base = QLineEdit()
        self._asr_base.setPlaceholderText(tr("enter_base_url"))
        form.addRow(_label(tr("base_url")), self._asr_base)

        self._asr_model = ThemedComboBox()
        self._asr_model.setEditable(True)
        self._asr_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._asr_model.lineEdit().setPlaceholderText(tr("enter_model"))
        form.addRow(_label(tr("model")), self._asr_model)

        lay.addWidget(group)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self._asr_test_btn = QPushButton(tr("test_connection"))
        self._asr_test_btn.clicked.connect(self._test_asr)
        self._asr_test_status = _hint(tr("not_tested"))
        test_row.addWidget(self._asr_test_btn)
        test_row.addWidget(self._asr_test_status, 1)
        lay.addLayout(test_row)

        self._asr_hint = _hint()
        lay.addWidget(self._asr_hint)
        return page

    def _build_asr_local_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        group = QGroupBox(tr("asr_local"))
        form = self._form(group)
        self._local_form = form

        self._local_backend = ThemedComboBox()
        for key in LOCAL_BACKENDS:
            preset = LOCAL_ASR_BACKENDS.get(key, {})
            self._local_backend.addItem(_preset_name(preset, key), key)
        form.addRow(_label(tr("asr_backend")), self._local_backend)

        self._whisper_model = ThemedComboBox()
        self._whisper_model.addItems(WHISPER_MODELS)
        form.addRow(_label(tr("whisper_model")), self._whisper_model)

        self._whisper_device = ThemedComboBox()
        self._whisper_device.addItems(WHISPER_DEVICES)
        form.addRow(_label(tr("device")), self._whisper_device)

        self._whisper_path = QLineEdit()
        self._whisper_path.setPlaceholderText("models/faster-whisper-base")
        self._whisper_row = self._path_row(self._whisper_path)
        form.addRow(_label(tr("whisper_model_path")), self._whisper_row)

        self._sherpa_path = QLineEdit()
        self._sherpa_path.setPlaceholderText("models/sherpa-streaming-zh-14M")
        self._sherpa_row = self._path_row(self._sherpa_path)
        form.addRow(_label(tr("sherpa_model_path")), self._sherpa_row)

        self._local_backend.currentIndexChanged.connect(self._on_local_backend_changed)
        lay.addWidget(group)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self._local_test_btn = QPushButton(tr("test_connection"))
        self._local_test_btn.setAutoDefault(False)
        self._local_test_btn.clicked.connect(self._test_local_asr)
        self._local_test_status = _hint(tr("not_tested"))
        test_row.addWidget(self._local_test_btn)
        test_row.addWidget(self._local_test_status, 1)
        lay.addLayout(test_row)

        self._gpu_info = _hint(tr("gpu_checking"))
        lay.addWidget(self._gpu_info)
        lay.addWidget(_hint(tr("asr_hint_local")))
        self._on_local_backend_changed()
        QTimer.singleShot(150, self._refresh_gpu_info)
        return page

    def _build_diarization_tab(self) -> QWidget:
        page, lay = self._tab_page()

        self._diar_enabled = ThemedCheckBox(tr("diarization_enabled"))
        self._diar_enabled.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay.addWidget(self._diar_enabled)

        self._diar_group = QGroupBox(tr("tab_diarization"))
        form = self._form(self._diar_group)

        self._diar_backend = ThemedComboBox()
        self._diar_backend.addItem(tr("diar_backend_sherpa"), "sherpa")
        self._diar_backend.addItem(tr("diar_backend_cluster"), "cluster")
        form.addRow(_label(tr("diarization_backend")), self._diar_backend)

        self._diar_max = ThemedSpinBox()
        self._diar_max.setRange(1, 6)
        form.addRow(_label(tr("max_speakers")), self._diar_max)

        self._diar_threshold = ThemedDoubleSpinBox()
        self._diar_threshold.setRange(0.0, 1.0)
        self._diar_threshold.setSingleStep(0.01)
        self._diar_threshold.setDecimals(2)
        self._diar_threshold.setSpecialValueText(tr("threshold_auto"))
        form.addRow(_label(tr("threshold")), self._diar_threshold)

        self._diar_min = ThemedDoubleSpinBox()
        self._diar_min.setRange(0.1, 3.0)
        self._diar_min.setSingleStep(0.1)
        self._diar_min.setDecimals(1)
        form.addRow(_label(tr("min_seconds")), self._diar_min)

        self._diar_model = QLineEdit()
        self._diar_model.setPlaceholderText(tr("optional"))
        form.addRow(_label(tr("diarization_model_path")), self._path_row(self._diar_model))

        lay.addWidget(self._diar_group)
        self._diar_down_hint = QLabel(tr("diar_down_hint"))
        self._diar_down_hint.setWordWrap(True)
        self._diar_down_hint.setStyleSheet("color: #fbbf24;")
        lay.addWidget(self._diar_down_hint)
        lay.addWidget(_hint(tr("diarization_hint")))
        lay.addStretch(1)
        self._diar_enabled.toggled.connect(self._on_diar_toggled)
        return page

    def _on_diar_toggled(self, enabled: bool):
        self._diar_group.setEnabled(enabled)
        self._diar_down_hint.setVisible(enabled)

    def _build_display_tab(self) -> QWidget:
        page, lay = self._tab_page()

        group = QGroupBox(tr("tab_display"))
        form = self._form(group)

        self._font_size = ThemedSpinBox()
        self._font_size.setRange(10, 48)
        form.addRow(_label(tr("font_size")), self._font_size)

        self._position_combo = ThemedComboBox()
        for value, key in zip(POSITIONS, ("pos_bottom", "pos_center", "pos_top")):
            self._position_combo.addItem(tr(key), value)
        form.addRow(_label(tr("position")), self._position_combo)

        self._screen_combo = ThemedComboBox()
        form.addRow(_label(tr("screen")), self._screen_combo)

        self._duration_spin = ThemedSpinBox()
        self._duration_spin.setRange(0, 30000)
        self._duration_spin.setSingleStep(1000)
        self._duration_spin.setSpecialValueText(tr("permanent"))
        form.addRow(_label(tr("subtitle_duration")), self._duration_spin)

        self._check_stream = ThemedCheckBox(tr("stream_translation"))
        form.addRow(_label(""), self._check_stream)

        self._check_speaker_colors = ThemedCheckBox(tr("speaker_colors"))
        form.addRow(_label(""), self._check_speaker_colors)
        for cb in (self._check_stream, self._check_speaker_colors):
            cb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        lay.addWidget(group)

        ui_group = QGroupBox(tr("ui_language"))
        ui_form = self._form(ui_group)
        self._ui_lang = ThemedComboBox()
        self._ui_lang.addItem(tr("ui_lang_auto"), "")
        self._ui_lang.addItem(tr("ui_lang_zh"), "zh")
        self._ui_lang.addItem(tr("ui_lang_en"), "en")
        ui_form.addRow(_label(tr("ui_language")), self._ui_lang)
        lay.addWidget(ui_group)

        lay.addStretch(1)
        return page

    def _build_audio_tab(self) -> QWidget:
        page, lay = self._tab_page()

        group = QGroupBox(tr("audio_devices"))
        form = self._form(group)

        self._device_list = QListWidget()
        self._device_list.setMinimumHeight(170)
        self._device_list.currentRowChanged.connect(self._on_device_selected)
        form.addRow(self._device_list)

        self._device_refresh = QPushButton(tr("audio_refresh"))
        self._device_refresh.setFixedWidth(110)
        self._device_refresh.clicked.connect(self._refresh_devices)
        refresh_row = QWidget()
        refresh_row.setObjectName("scrollContent")
        refresh_lay = QHBoxLayout(refresh_row)
        refresh_lay.setContentsMargins(0, 0, 0, 0)
        refresh_lay.addStretch(1)
        refresh_lay.addWidget(self._device_refresh)
        form.addRow(_label(""), refresh_row)

        self._device_info = _hint("")
        form.addRow(self._device_info)

        lay.addWidget(group)
        lay.addWidget(_hint(tr("audio_hint")))
        lay.addStretch(1)
        self._refresh_devices()
        return page

    def _build_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText(tr("apply"))
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._save)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        for button in buttons.buttons():
            if isinstance(button, QPushButton) and button is not buttons.button(
                QDialogButtonBox.StandardButton.Ok
            ):
                button.setAutoDefault(False)
        return buttons

    def _path_row(self, edit: QLineEdit) -> QWidget:
        row = QWidget()
        row.setObjectName("scrollContent")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        btn = QPushButton(tr("browse"))
        btn.clicked.connect(lambda: self._browse_dir(edit))
        h.addWidget(edit, 1)
        h.addWidget(btn, 0)
        return row

    # ── 交互 ──────────────────────────────────────────

    def _lang_label(self, value: str) -> str:
        return {
            "auto": tr("auto"),
            "zh": tr("chinese_zh"),
            "en": tr("english_en"),
            "ja": tr("japanese_ja"),
        }.get(value, value)

    @staticmethod
    def _fill_models(combo: QComboBox, models: list[str], current: str):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(models)
        if current:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def _on_translation_provider_changed(self):
        key = self._tr_provider.currentData()
        preset = TRANSLATION_PRESETS.get(key, {})
        self._tr_base.setText(preset.get("base_url", ""))
        self._fill_models(self._tr_model, list(preset.get("models", [])), preset.get("default_model", ""))
        self._tr_key.setPlaceholderText(
            tr("enter_key") if preset.get("requires_key", True) else tr("provider_hint_no_key", name="")
        )
        self._update_translator_hint()

    def _update_translator_hint(self):
        key = self._tr_provider.currentData()
        preset = TRANSLATION_PRESETS.get(key, {})
        name = _preset_name(preset, key or "custom")
        if key == "custom":
            text = tr("endpoint_custom_hint")
        elif preset.get("requires_key", True):
            text = tr("provider_hint", name=name, url=preset.get("base_url") or "-")
        else:
            text = tr("provider_hint_no_key", name=name)
        self._tr_hint.setText(text)

    def _on_asr_provider_changed(self):
        key = self._asr_provider.currentData()
        preset = ASR_PRESETS.get(key, {})
        self._asr_base.setText(preset.get("base_url", ""))
        self._fill_models(self._asr_model, list(preset.get("models", [])), preset.get("default_model", ""))
        self._update_asr_hint()

    def _update_asr_hint(self):
        key = self._asr_provider.currentData()
        preset = ASR_PRESETS.get(key, {})
        if preset.get("protocol") == "mimo":
            self._asr_hint.setText(tr("asr_hint_mimo"))
        else:
            self._asr_hint.setText(tr("asr_hint_openai"))

    def _on_asr_mode_changed(self, cloud: bool):
        self._asr_stack.setCurrentIndex(0 if cloud else 1)

    def _on_local_backend_changed(self):
        backend = self._local_backend.currentData()
        whisper = backend == "whisper"
        sherpa = backend == "sherpa"
        self._whisper_model.setEnabled(whisper)
        self._whisper_device.setEnabled(whisper)
        self._whisper_row.setEnabled(whisper)
        self._sherpa_row.setEnabled(sherpa)
        # 只显示当前后端需要的字段，避免首屏把“测试连接”挤出视口
        self._local_form.setRowVisible(1, whisper)
        self._local_form.setRowVisible(2, whisper)
        self._local_form.setRowVisible(3, whisper)
        self._local_form.setRowVisible(4, sherpa)

    def _browse_dir(self, edit: QLineEdit):
        start = edit.text().strip() or str(app_dir())
        path = QFileDialog.getExistingDirectory(self, tr("browse"), start)
        if path:
            edit.setText(path)

    def _refresh_devices(self):
        current = self._device_list.currentItem()
        current_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._device_list.blockSignals(True)
        self._device_list.clear()
        auto_item = QListWidgetItem(tr("audio_auto"))
        auto_item.setData(Qt.ItemDataRole.UserRole, "auto")
        self._device_list.addItem(auto_item)
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
                    item = QListWidgetItem("[%d] %s" % (i, d["name"]))
                    item.setData(Qt.ItemDataRole.UserRole, i)
                    self._device_list.addItem(item)
        except Exception as e:
            logger.warning("Failed to enumerate audio devices: %s", e)
            self._device_info.setText(tr("audio_no_devices"))
        self._device_list.blockSignals(False)
        self._select_device(current_id)

    def _select_device(self, value):
        for row in range(self._device_list.count()):
            item = self._device_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == str(value):
                self._device_list.setCurrentRow(row)
                return
        self._device_list.setCurrentRow(0)

    def _on_device_selected(self, row: int):
        item = self._device_list.item(row)
        if item is None:
            return
        dev_id = item.data(Qt.ItemDataRole.UserRole)
        if dev_id == "auto":
            self._device_info.setText("")
            return
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

    def _refresh_gpu_info(self):
        cfg = get_config().asr
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                total = getattr(props, "total_memory", None) or getattr(props, "total_mem", 0)
                mem = int(total) // (1024**3)
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

    # ── 测试连接 ──────────────────────────────────────

    def _set_test_state(self, button: QPushButton, label: QLabel, running: bool):
        button.setEnabled(not running)
        button.setText(tr("test_progress") if running else tr("test_connection"))
        label.setText(tr("test_progress") if running else label.text())

    def _run_test(self, button: QPushButton, label: QLabel, worker):
        self._set_test_state(button, label, True)

        def _run():
            try:
                ok, detail = worker()
            except Exception as e:
                ok, detail = False, tr("test_request_failed", error=e)
            QTimer.singleShot(0, lambda: self._on_test_done(button, label, ok, detail))

        threading.Thread(target=_run, daemon=True).start()

    def _on_test_done(self, button: QPushButton, label: QLabel, ok: bool, detail: str):
        button.setEnabled(True)
        button.setText(tr("test_connection"))
        label.setText(("\u2714 " if ok else "\u2716 ") + detail)
        label.setToolTip(detail)
        label.setStyleSheet("color: %s;" % ("#34d399" if ok else "#fb7185"))

    def _test_translator(self):
        key = self._tr_key.text().strip()
        provider = self._tr_provider.currentData()
        preset = TRANSLATION_PRESETS.get(provider, {})
        name = _preset_name(preset, provider or "custom")
        if preset.get("requires_key", True) and not key:
            QMessageBox.warning(self, tr("test_fail"), tr("test_enter_key", name=name))
            return
        base = self._tr_base.text().strip()
        model = self._tr_model.currentText().strip()
        if not base:
            QMessageBox.warning(self, tr("test_fail"), tr("test_enter_base_url"))
            return
        if not model:
            QMessageBox.warning(self, tr("test_fail"), tr("test_enter_model"))
            return

        url = normalize_api_url(base) + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        }

        def worker():
            with httpx.Client(timeout=15.0) as client:
                return _http_result(client.post(url, json=body, headers=headers))

        self._run_test(self._tr_test_btn, self._tr_test_status, worker)

    def _test_asr(self):
        key = self._asr_key.text().strip()
        provider = self._asr_provider.currentData()
        preset = ASR_PRESETS.get(provider, {})
        name = _preset_name(preset, provider or "custom")
        if preset.get("requires_key", True) and not key:
            QMessageBox.warning(self, tr("test_fail"), tr("test_enter_key", name=name))
            return
        base = self._asr_base.text().strip()
        model = self._asr_model.currentText().strip()
        if not base:
            QMessageBox.warning(self, tr("test_fail"), tr("test_enter_base_url"))
            return
        if not model:
            QMessageBox.warning(self, tr("test_fail"), tr("test_enter_model"))
            return

        normalized = normalize_api_url(base)
        protocol = preset.get("protocol", "openai")
        wav = pcm_to_wav(b"\x00\x00" * 16000)

        def worker():
            with httpx.Client(timeout=20.0) as client:
                if protocol == "mimo":
                    import base64
                    data_url = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
                    body = {
                        "model": model,
                        "messages": [{
                            "role": "user",
                            "content": [{
                                "type": "input_audio",
                                "input_audio": {"data": data_url},
                            }],
                        }],
                        "max_tokens": 1,
                    }
                    headers = {"api-key": key, "Content-Type": "application/json"}
                    return _http_result(
                        client.post(normalized + "/chat/completions", json=body, headers=headers)
                    )
                headers = {}
                if key:
                    headers["Authorization"] = "Bearer " + key
                return _http_result(
                    client.post(
                        normalized + "/audio/transcriptions",
                        headers=headers,
                        files={"file": ("test.wav", wav, "audio/wav")},
                        data={"model": model, "response_format": "verbose_json"},
                    )
                )

        self._run_test(self._asr_test_btn, self._asr_test_status, worker)

    def _test_local_asr(self):
        backend = self._local_backend.currentData()
        whisper_path = self._whisper_path.text().strip() or "models/faster-whisper-base"
        sherpa_path = self._sherpa_path.text().strip() or "models/sherpa-streaming-zh-14M"

        def worker():
            if backend == "mock":
                return True, tr("test_local_ok")
            if backend == "whisper":
                path = _resolve(whisper_path)
                if (path / "model.bin").exists():
                    return True, tr("test_local_ok")
                return False, tr("test_local_missing", path=str(path))
            path = _resolve(sherpa_path)
            has_tokens = (path / "tokens.txt").exists()
            has_onnx = any(path.glob("*.onnx")) if path.exists() else False
            if has_tokens and has_onnx:
                return True, tr("test_local_ok")
            return False, tr("test_local_missing", path=str(path))

        self._run_test(self._local_test_btn, self._local_test_status, worker)

    # ── 读取 / 保存 ───────────────────────────────────

    def _load_values(self):
        cfg = get_config()

        # 翻译
        tr_keys = [self._tr_provider.itemData(i) for i in range(self._tr_provider.count())]
        provider = cfg.translator.provider if cfg.translator.provider in tr_keys else "custom"
        self._tr_provider.blockSignals(True)
        self._tr_provider.setCurrentIndex(tr_keys.index(provider))
        self._tr_provider.blockSignals(False)
        preset = TRANSLATION_PRESETS.get(provider, {})
        self._tr_key.setText(cfg.translator.api_key)
        self._tr_base.setText(cfg.translator.base_url or preset.get("base_url", ""))
        self._fill_models(
            self._tr_model,
            list(preset.get("models", [])),
            cfg.translator.model or preset.get("default_model", ""),
        )
        self._tr_temp.setValue(float(cfg.translator.temperature))
        self._tr_max_tokens.setValue(int(cfg.translator.max_tokens))
        self._update_translator_hint()

        source = cfg.asr.language if cfg.asr.language in SOURCE_LANGS else "auto"
        self._source_lang.setCurrentIndex(SOURCE_LANGS.index(source))
        self._target_lang.setText(cfg.translator.target_language)

        # ASR
        local = cfg.asr.is_local
        self._asr_cloud_radio.setChecked(not local)
        self._asr_local_radio.setChecked(local)
        self._asr_stack.setCurrentIndex(1 if local else 0)
        if local:
            backend = cfg.asr.backend if cfg.asr.backend in LOCAL_BACKENDS else "whisper"
            self._local_backend.setCurrentIndex(LOCAL_BACKENDS.index(backend))
            self._whisper_model.setCurrentText(cfg.asr.whisper_model)
            self._whisper_device.setCurrentText(cfg.asr.whisper_device)
            self._whisper_path.setText(cfg.asr.whisper_model_path)
            self._sherpa_path.setText(cfg.asr.sherpa_model_path)
        else:
            asr_keys = [self._asr_provider.itemData(i) for i in range(self._asr_provider.count())]
            backend = cfg.asr.backend if cfg.asr.backend in asr_keys else "custom"
            self._asr_provider.blockSignals(True)
            self._asr_provider.setCurrentIndex(asr_keys.index(backend))
            self._asr_provider.blockSignals(False)
            apreset = ASR_PRESETS.get(backend, {})
            self._asr_key.setText(cfg.asr.api_key)
            self._asr_base.setText(cfg.asr.base_url or apreset.get("base_url", ""))
            self._fill_models(
                self._asr_model,
                list(apreset.get("models", [])),
                cfg.asr.model or apreset.get("default_model", ""),
            )
            self._update_asr_hint()
        self._skip_translate.setChecked(cfg.asr.skip_translate_when_same_lang)

        # 说话人
        d = cfg.diarization
        self._diar_enabled.setChecked(d.enabled)
        self._diar_group.setEnabled(d.enabled)
        self._diar_down_hint.setVisible(d.enabled)
        self._diar_backend.setCurrentIndex(0 if d.backend != "cluster" else 1)
        self._diar_max.setValue(int(d.max_speakers))
        if d.threshold:
            self._diar_threshold.setValue(float(d.threshold))
        else:
            self._diar_threshold.setValue(0.0)
        self._diar_min.setValue(float(d.min_seconds))
        self._diar_model.setText(d.model_path)

        # 显示
        disp = cfg.display
        self._font_size.setValue(int(disp.font_size))
        self._duration_spin.setValue(int(disp.subtitle_duration_ms))
        self._duration_spin.setEnabled(True)
        position = disp.subtitle_position if disp.subtitle_position in POSITIONS else "bottom"
        self._position_combo.setCurrentIndex(POSITIONS.index(position))
        self._check_stream.setChecked(disp.stream_translation)
        self._check_speaker_colors.setChecked(disp.speaker_colors)

        screens = QApplication.screens()
        self._screen_combo.clear()
        for i in range(len(screens)):
            self._screen_combo.addItem(
                tr("screen_primary") if i == 0 else tr("screen_n", n=i + 1), i
            )
        try:
            screen_index = int(disp.subtitle_screen)
        except (TypeError, ValueError):
            screen_index = 0
        if 0 <= screen_index < len(screens):
            self._screen_combo.setCurrentIndex(screen_index)

        ui_lang = self._env.get("UI_LANGUAGE", "").strip().lower()
        self._ui_lang.setCurrentIndex({"": 0, "zh": 1, "en": 2}.get(ui_lang, 0))

        self._select_device(cfg.audio_device)

    def _save(self):
        env = read_env_file()

        provider = self._tr_provider.currentData() or "custom"
        env["TRANSLATOR_PROVIDER"] = provider
        env["TRANSLATOR_API_KEY"] = self._tr_key.text().strip()
        env["TRANSLATOR_BASE_URL"] = self._tr_base.text().strip()
        env["TRANSLATOR_MODEL"] = self._tr_model.currentText().strip()
        env["TRANSLATOR_TEMPERATURE"] = ("%.2f" % self._tr_temp.value()).rstrip("0").rstrip(".")
        env["TRANSLATOR_MAX_TOKENS"] = str(self._tr_max_tokens.value())
        env["TARGET_LANGUAGE"] = self._target_lang.text().strip() or "中文"
        env["SOURCE_LANGUAGE"] = self._source_lang.currentData() or "auto"

        if self._asr_cloud_radio.isChecked():
            asr_provider = self._asr_provider.currentData() or "custom"
            env["ASR_BACKEND"] = asr_provider
            env["ASR_API_KEY"] = self._asr_key.text().strip()
            env["ASR_BASE_URL"] = self._asr_base.text().strip()
            env["ASR_MODEL"] = self._asr_model.currentText().strip()
        else:
            env["ASR_BACKEND"] = self._local_backend.currentData() or "whisper"

        env["WHISPER_MODEL"] = self._whisper_model.currentText().strip() or "base"
        env["WHISPER_DEVICE"] = self._whisper_device.currentText().strip() or "auto"
        env["WHISPER_MODEL_PATH"] = (
            self._whisper_path.text().strip() or "models/faster-whisper-base"
        )
        env["SHERPA_MODEL_PATH"] = (
            self._sherpa_path.text().strip() or "models/sherpa-streaming-zh-14M"
        )
        env["SKIP_TRANSLATE_SAME_LANG"] = (
            "true" if self._skip_translate.isChecked() else "false"
        )

        env["DIARIZATION_ENABLED"] = "true" if self._diar_enabled.isChecked() else "false"
        env["DIARIZATION_BACKEND"] = self._diar_backend.currentData() or "sherpa"
        env["DIARIZATION_MAX_SPEAKERS"] = str(self._diar_max.value())
        threshold = self._diar_threshold.value()
        env["DIARIZATION_THRESHOLD"] = "" if threshold <= 0 else "%.2f" % threshold
        env["DIARIZATION_MIN_SECONDS"] = "%.1f" % self._diar_min.value()
        env["DIARIZATION_MODEL_PATH"] = self._diar_model.text().strip()

        env["FONT_SIZE"] = str(self._font_size.value())
        env["SUBTITLE_DURATION"] = str(self._duration_spin.value())
        env["SUBTITLE_POSITION"] = self._position_combo.currentData() or "bottom"
        env["SUBTITLE_SCREEN"] = str(self._screen_combo.currentData() or 0)
        env["STREAM_TRANSLATION"] = "true" if self._check_stream.isChecked() else "false"
        env["SPEAKER_COLORS"] = "true" if self._check_speaker_colors.isChecked() else "false"

        env["UI_LANGUAGE"] = self._ui_lang.currentData() or ""

        item = self._device_list.currentItem()
        device = item.data(Qt.ItemDataRole.UserRole) if item is not None else "auto"
        env["AUDIO_DEVICE"] = str(device) if device is not None else "auto"

        write_env_file(env)
        import dotenv
        dotenv.load_dotenv(env_path(), override=True)
        reload_config()
        reload_language()
        logger.info("Settings saved: translator=%s asr=%s", provider, env.get("ASR_BACKEND"))

    def _save_and_close(self):
        self._save()
        self.accept()
