"""
登录窗口 —— 输入 API Key 验证后进入主程序。

课程设计要求：QLineEdit、QCheckBox、QPushButton、QLabel。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QLabel,
    QMessageBox,
    QGroupBox,
)


class LoginDialog(QDialog):
    """Vocis 登录窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vocis · 声幕 — 登录")
        self.setFixedSize(420, 340)

        # 加载已有配置
        self._env = self._read_env()

        self._build_ui()
        self._load_saved()

        # 窗口图标
        icon_path = Path(__file__).parent.parent / "assets" / "vocis_32.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _read_env(self) -> dict:
        env = {}
        path = Path(__file__).parent.parent / ".env"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
        return env

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("Vocis · 声幕")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)

        subtitle = QLabel("实时语音识别 + AI 翻译字幕")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 10px;")
        layout.addWidget(subtitle)

        # API Key 组
        api_group = QGroupBox("API 密钥配置")
        api_form = QFormLayout(api_group)

        self._mimo_edit = QLineEdit()
        self._mimo_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._mimo_edit.setPlaceholderText("输入 MiMo API Key")
        api_form.addRow("MiMo ASR:", self._mimo_edit)

        self._deepseek_edit = QLineEdit()
        self._deepseek_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._deepseek_edit.setPlaceholderText("输入 DeepSeek API Key")
        api_form.addRow("DeepSeek:", self._deepseek_edit)

        layout.addWidget(api_group)

        # 复选框：记住密钥
        self._remember_check = QCheckBox("记住密钥（保存到 .env 文件）")
        self._remember_check.setChecked(True)
        layout.addWidget(self._remember_check)

        layout.addSpacing(10)

        # 按钮
        btn_layout = QHBoxLayout()

        self._login_btn = QPushButton("登  录")
        self._login_btn.setDefault(True)
        self._login_btn.clicked.connect(self._on_login)
        self._login_btn.setStyleSheet("QPushButton { padding: 6px 30px; font-weight: bold; }")

        self._skip_btn = QPushButton("跳过（离线模式）")
        self._skip_btn.clicked.connect(self._on_skip)

        btn_layout.addWidget(self._skip_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._login_btn)
        layout.addLayout(btn_layout)

    def _load_saved(self):
        if self._env.get("MIMO_API_KEY"):
            self._mimo_edit.setText(self._env["MIMO_API_KEY"])
        if self._env.get("DEEPSEEK_API_KEY"):
            self._deepseek_edit.setText(self._env["DEEPSEEK_API_KEY"])

    def _on_login(self):
        mimo = self._mimo_edit.text().strip()
        deepseek = self._deepseek_edit.text().strip()

        if not mimo and not deepseek:
            QMessageBox.warning(self, "提示", "请至少输入一组 API Key，或选择「跳过」。")
            return

        if self._remember_check.isChecked():
            self._save_keys(mimo, deepseek)

        self.accept()

    def _on_skip(self):
        if self._remember_check.isChecked():
            self._save_keys(
                self._mimo_edit.text().strip(),
                self._deepseek_edit.text().strip(),
            )
        self.accept()

    def _save_keys(self, mimo: str, deepseek: str):
        env = self._read_env()
        if mimo:
            env["MIMO_API_KEY"] = mimo
        if deepseek:
            env["DEEPSEEK_API_KEY"] = deepseek

        path = Path(__file__).parent.parent / ".env"
        lines = [f"{k}={v}\n" for k, v in env.items()]
        path.write_text("".join(lines), encoding="utf-8")

    def get_keys(self) -> tuple:
        return (
            self._mimo_edit.text().strip(),
            self._deepseek_edit.text().strip(),
        )
