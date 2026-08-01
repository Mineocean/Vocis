"""First-run setup wizard — guides API key configuration."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
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
from gui.i18n import tr


class SetupWizard(QDialog):
    """First-run setup wizard for API key configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("wizard_title"))
        self.setFixedSize(480, 380)

        self._env = read_env_file()
        self._build_ui()

        icon_path = app_dir() / "assets" / "vocis_32.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_welcome_page())
        self._stack.addWidget(self._build_keys_page())
        self._stack.addWidget(self._build_done_page())
        layout.addWidget(self._stack)

        nav = QHBoxLayout()
        self._back_btn = QPushButton(tr("wizard_back"))
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn = QPushButton(tr("wizard_next"))
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self._go_next)
        self._skip_btn = QPushButton(tr("wizard_skip"))
        self._skip_btn.clicked.connect(self._skip)

        nav.addWidget(self._back_btn)
        nav.addStretch()
        nav.addWidget(self._skip_btn)
        nav.addWidget(self._next_btn)
        layout.addLayout(nav)

        self._update_nav()

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel(tr("wizard_welcome"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; margin: 20px 0;")
        layout.addWidget(title)

        desc = QLabel(tr("wizard_desc"))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()
        return page

    def _build_keys_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel(tr("wizard_api_config"))
        title.setStyleSheet("font-size: 16px; font-weight: 600; margin-bottom: 8px;")
        layout.addWidget(title)

        # MiMo ASR
        mimo_group = QGroupBox(tr("wizard_mimo_group"))
        mimo_form = QFormLayout(mimo_group)
        self._mimo_key = QLineEdit()
        self._mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._mimo_key.setPlaceholderText(tr("wizard_mimo_ph"))
        mimo_form.addRow(tr("enter_mimo_key"), self._mimo_key)
        layout.addWidget(mimo_group)

        # DeepSeek
        ds_group = QGroupBox(tr("wizard_ds_group"))
        ds_form = QFormLayout(ds_group)
        self._ds_key = QLineEdit()
        self._ds_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ds_key.setPlaceholderText(tr("wizard_ds_ph"))
        ds_form.addRow(tr("enter_ds_key"), self._ds_key)
        layout.addWidget(ds_group)

        self._remember = QCheckBox(tr("wizard_remember"))
        self._remember.setChecked(True)
        layout.addWidget(self._remember)

        layout.addStretch()
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel(tr("wizard_complete"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; margin: 20px 0;")
        layout.addWidget(title)

        info = QLabel(tr("wizard_ready"))
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addStretch()
        return page

    def _update_nav(self):
        idx = self._stack.currentIndex()
        self._back_btn.setVisible(idx > 0)
        self._skip_btn.setVisible(idx < 2)
        self._next_btn.setText(tr("wizard_finish") if idx == 2 else tr("wizard_next"))

    def _go_back(self):
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
        self._update_nav()

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx < 2:
            if idx == 1:  # Keys page — save
                self._save_keys()
            self._stack.setCurrentIndex(idx + 1)
        else:
            self.accept()
        self._update_nav()

    def _skip(self):
        idx = self._stack.currentIndex()
        if idx == 1:
            self._save_keys()
        self.accept()

    def _save_keys(self):
        if not self._remember.isChecked():
            return
        env = read_env_file()
        mimo = self._mimo_key.text().strip()
        ds = self._ds_key.text().strip()
        if mimo:
            env["MIMO_API_KEY"] = mimo
        if ds:
            env["DEEPSEEK_API_KEY"] = ds
        write_env_file(env)
