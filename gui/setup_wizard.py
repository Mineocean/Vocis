"""First-run setup wizard — 选择翻译提供商，可选配置语音识别。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.config import app_dir, read_env_file, write_env_file
from backend.providers.presets import ASR_PRESETS, LOCAL_ASR_BACKENDS, TRANSLATION_PRESETS
from gui.i18n import current_language, tr
from gui.widgets import ThemedCheckBox, ThemedComboBox

LOCAL_BACKENDS = ["whisper", "sherpa", "mock"]
CLOUD_ASR = ["mimo", "openai", "groq", "siliconflow", "custom"]


def _preset_name(preset: dict, fallback: str = "") -> str:
    key = "name_zh" if current_language() == "zh" else "name"
    return preset.get(key) or preset.get("name") or fallback


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("formLabel")
    return lbl


def _hint(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


class SetupWizard(QDialog):
    """First-run setup wizard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("wizard_title"))
        self.resize(640, 560)
        self.setMinimumSize(600, 520)

        self._env = read_env_file()
        self._build_ui()

        icon_path = app_dir() / "assets" / "vocis_32.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_welcome_page())
        self._stack.addWidget(self._build_translate_page())
        self._stack.addWidget(self._build_asr_page())
        self._stack.addWidget(self._build_done_page())
        self._stack.currentChanged.connect(self._update_nav)
        layout.addWidget(self._stack, 1)

        nav = QHBoxLayout()
        nav.setSpacing(8)
        self._back_btn = QPushButton(tr("wizard_back"))
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn = QPushButton(tr("wizard_next"))
        self._next_btn.setObjectName("primary")
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self._go_next)
        self._skip_btn = QPushButton(tr("wizard_skip"))
        self._skip_btn.setObjectName("link")
        self._skip_btn.setAutoDefault(False)
        self._skip_btn.clicked.connect(self._skip)

        self._step_label = QLabel("")
        self._step_label.setObjectName("hint")

        nav.addWidget(self._back_btn)
        nav.addWidget(self._step_label)
        nav.addStretch(1)
        nav.addWidget(self._skip_btn)
        nav.addWidget(self._next_btn)
        layout.addLayout(nav)

        self._update_nav()

    # ── 页面 ──────────────────────────────────────────

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
        layout.addStretch(1)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = app_dir() / "assets" / "vocis_128.png"
        if logo_path.exists():
            pm = QPixmap(str(logo_path)).scaled(
                88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pm)
        layout.addWidget(logo)

        title = QLabel(tr("wizard_welcome"))
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = _hint(tr("wizard_desc"))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        layout.addStretch(1)
        return page

    def _build_translate_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        title = QLabel(tr("wizard_translate"))
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        group = QGroupBox(tr("wizard_api_config"))
        form = QFormLayout(group)
        form.setContentsMargins(14, 8, 14, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._provider = ThemedComboBox()
        for key, preset in TRANSLATION_PRESETS.items():
            self._provider.addItem(_preset_name(preset, key), key)
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(_label(tr("provider")), self._provider)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText(tr("enter_key"))
        form.addRow(_label(tr("api_key")), self._key)

        self._key_err = QLabel("")
        self._key_err.setStyleSheet("color: #fb7185;")
        self._key_err.setWordWrap(True)
        form.addRow(_label(""), self._key_err)
        self._key_form = form
        form.setRowVisible(2, False)

        self._base = QLineEdit()
        self._base.setPlaceholderText(tr("enter_base_url"))
        form.addRow(_label(tr("base_url")), self._base)

        self._model = ThemedComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(ThemedComboBox.InsertPolicy.NoInsert)
        form.addRow(_label(tr("model")), self._model)

        self._target_lang = ThemedComboBox()
        for value in ("中文", "English", "日本語"):
            self._target_lang.addItem(value, value)
        current = self._env.get("TARGET_LANGUAGE") or "中文"
        index = self._target_lang.findData(current)
        if index >= 0:
            self._target_lang.setCurrentIndex(index)
        form.addRow(_label(tr("wizard_target_language")), self._target_lang)

        layout.addWidget(group)
        layout.addWidget(_hint(tr("wizard_provider_hint")))

        self._remember = ThemedCheckBox(tr("wizard_remember"))
        self._remember.setChecked(True)
        layout.addWidget(self._remember)
        layout.addStretch(1)

        provider = self._env.get("TRANSLATOR_PROVIDER") or "deepseek"
        self._apply_provider(provider)
        if self._env.get("TRANSLATOR_API_KEY"):
            self._key.setText(self._env["TRANSLATOR_API_KEY"])
        if self._env.get("TRANSLATOR_BASE_URL"):
            self._base.setText(self._env["TRANSLATOR_BASE_URL"])
        if self._env.get("TRANSLATOR_MODEL"):
            self._model.setCurrentText(self._env["TRANSLATOR_MODEL"])
        return page

    def _build_asr_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        title = QLabel(tr("wizard_asr"))
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        mode_group = QGroupBox(tr("wizard_asr_mode"))
        mode_form = QFormLayout(mode_group)
        mode_form.setContentsMargins(14, 8, 14, 8)
        mode_form.setHorizontalSpacing(12)
        mode_form.setVerticalSpacing(10)
        self._asr_mode = ThemedComboBox()
        self._asr_mode.addItem(tr("wizard_asr_later"), "later")
        self._asr_mode.addItem(tr("wizard_asr_local"), "local")
        self._asr_mode.addItem(tr("wizard_asr_cloud"), "cloud")
        self._asr_mode.currentIndexChanged.connect(self._on_asr_mode_changed)
        mode_form.addRow(_label(tr("wizard_asr_mode")), self._asr_mode)
        layout.addWidget(mode_group)

        self._asr_stack = QStackedWidget()
        self._asr_stack.addWidget(self._build_asr_later_page())
        self._asr_stack.addWidget(self._build_asr_local_page())
        self._asr_stack.addWidget(self._build_asr_cloud_page())
        layout.addWidget(self._asr_stack, 1)
        layout.addStretch(1)
        return page

    def _build_asr_later_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.addWidget(_hint(tr("wizard_cloud_hint")))
        layout.addStretch(1)
        return page

    def _build_asr_local_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)

        group = QGroupBox(tr("asr_local"))
        form = QFormLayout(group)
        form.setContentsMargins(14, 8, 14, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self._local_backend = ThemedComboBox()
        for key in LOCAL_BACKENDS:
            self._local_backend.addItem(_preset_name(LOCAL_ASR_BACKENDS.get(key, {}), key), key)
        form.addRow(_label(tr("asr_backend")), self._local_backend)
        layout.addWidget(group)
        layout.addWidget(_hint(tr("wizard_local_hint")))
        return page

    def _build_asr_cloud_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)

        group = QGroupBox(tr("asr_cloud"))
        form = QFormLayout(group)
        form.setContentsMargins(14, 8, 14, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._asr_provider = ThemedComboBox()
        for key in CLOUD_ASR:
            self._asr_provider.addItem(_preset_name(ASR_PRESETS.get(key, {}), key), key)
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
        self._asr_model.setInsertPolicy(ThemedComboBox.InsertPolicy.NoInsert)
        form.addRow(_label(tr("model")), self._asr_model)

        layout.addWidget(group)
        self._apply_asr_provider("mimo")
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scrollContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 30, 10, 10)
        layout.setSpacing(12)

        title = QLabel(tr("wizard_complete"))
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._done_info = _hint(tr("wizard_ready"))
        self._done_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._done_info)
        layout.addStretch(1)
        return page

    # ── 逻辑 ──────────────────────────────────────────

    def _apply_provider(self, key: str):
        keys = [self._provider.itemData(i) for i in range(self._provider.count())]
        if key not in keys:
            key = "deepseek"
        self._provider.blockSignals(True)
        self._provider.setCurrentIndex(keys.index(key))
        self._provider.blockSignals(False)
        preset = TRANSLATION_PRESETS.get(key, {})
        self._base.setText(preset.get("base_url", ""))
        self._model.blockSignals(True)
        self._model.clear()
        self._model.addItems(list(preset.get("models", [])))
        if preset.get("default_model"):
            self._model.setCurrentText(preset["default_model"])
        self._model.blockSignals(False)

    def _apply_asr_provider(self, key: str):
        keys = [self._asr_provider.itemData(i) for i in range(self._asr_provider.count())]
        if key not in keys:
            key = "mimo"
        self._asr_provider.blockSignals(True)
        self._asr_provider.setCurrentIndex(keys.index(key))
        self._asr_provider.blockSignals(False)
        preset = ASR_PRESETS.get(key, {})
        self._asr_base.setText(preset.get("base_url", ""))
        self._asr_model.blockSignals(True)
        self._asr_model.clear()
        self._asr_model.addItems(list(preset.get("models", [])))
        if preset.get("default_model"):
            self._asr_model.setCurrentText(preset["default_model"])
        self._asr_model.blockSignals(False)

    def _on_provider_changed(self):
        self._apply_provider(self._provider.currentData())

    def _on_asr_provider_changed(self):
        self._apply_asr_provider(self._asr_provider.currentData())

    def _on_asr_mode_changed(self, idx: int):
        self._asr_stack.setCurrentIndex(max(0, min(2, idx)))

    def _update_nav(self):
        idx = self._stack.currentIndex()
        self._back_btn.setVisible(0 < idx < 3)
        self._skip_btn.setVisible(1 <= idx < 3)
        self._next_btn.setText(tr("wizard_finish") if idx == 3 else tr("wizard_next"))
        self._step_label.setVisible(1 <= idx <= 2)
        if 1 <= idx <= 2:
            self._step_label.setText(tr("wizard_step", n=idx, total=2))
        self._next_btn.setDefault(True)
        self._skip_btn.setAutoDefault(False)
        if idx == 1:
            self._key.setFocus()
        elif idx in (0, 2, 3):
            self._next_btn.setFocus()

    def _go_back(self):
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)

    def _provider_requires_key(self) -> bool:
        preset = TRANSLATION_PRESETS.get(self._provider.currentData(), {})
        return bool(preset.get("requires_key", True))

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx == 1:
            name = _preset_name(
                TRANSLATION_PRESETS.get(self._provider.currentData(), {}),
                self._provider.currentData() or "",
            )
            if self._provider_requires_key() and not self._key.text().strip():
                self._key_err.setText(tr("wizard_need_key", name=name))
                self._key_form.setRowVisible(2, True)
                self._key.setFocus()
                return
            self._key_form.setRowVisible(2, False)
            self._save()
            self._stack.setCurrentIndex(2)
        elif idx < 2:
            self._stack.setCurrentIndex(idx + 1)
        elif idx == 2:
            self._save()
            self._stack.setCurrentIndex(3)
        else:
            self.accept()

    def _skip(self):
        idx = self._stack.currentIndex()
        if idx == 1:
            # 未填 Key 也能先开始，但不再谎报「已就绪」
            configured = bool(self._key.text().strip())
            if configured:
                self._save()
            self._done_info.setText(
                tr("wizard_ready") if configured else tr("wizard_skipped_ready")
            )
            self._stack.setCurrentIndex(3)
        elif idx == 2:
            self._save()
            self._stack.setCurrentIndex(3)

    def _save(self):
        if not self._remember.isChecked():
            return
        env = read_env_file()
        provider = self._provider.currentData() or "deepseek"
        env["TRANSLATOR_PROVIDER"] = provider
        env["TRANSLATOR_API_KEY"] = self._key.text().strip()
        env["TRANSLATOR_BASE_URL"] = self._base.text().strip()
        env["TRANSLATOR_MODEL"] = self._model.currentText().strip()
        env["TARGET_LANGUAGE"] = self._target_lang.currentData() or "中文"

        mode = self._asr_mode.currentData()
        if mode == "local":
            backend = self._local_backend.currentData() or "whisper"
            env["ASR_BACKEND"] = backend
            env.setdefault("WHISPER_MODEL", "base")
            env.setdefault("WHISPER_DEVICE", "auto")
            env.setdefault("WHISPER_MODEL_PATH", "models/faster-whisper-base")
            env.setdefault("SHERPA_MODEL_PATH", "models/sherpa-streaming-zh-14M")
        elif mode == "cloud":
            backend = self._asr_provider.currentData() or "mimo"
            env["ASR_BACKEND"] = backend
            env["ASR_API_KEY"] = self._asr_key.text().strip()
            env["ASR_BASE_URL"] = self._asr_base.text().strip()
            env["ASR_MODEL"] = self._asr_model.currentText().strip()
        write_env_file(env)
        self._env = env
