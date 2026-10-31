"""
主控制面板 —— 状态、当前配置、说话人图例、暂停/继续、设置入口。

由托盘图标双击左键打开；关闭窗口时隐藏而非退出，保持托盘常驻。
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.config import app_dir, get_config
from backend.providers.presets import (
    ASR_PRESETS,
    LOCAL_ASR_BACKENDS,
    TRANSLATION_PRESETS,
    asr_preset,
    translation_preset,
)
from gui.i18n import current_language, tr
from gui.theme import FONT_FAMILIES, speaker_color
from gui.widgets import ThemedComboBox

logger = logging.getLogger(__name__)

LANGS = ["auto", "zh", "en", "ja"]


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


class MainWindow(QWidget):
    """Vocis 主控制面板。"""

    def __init__(self, tray_manager=None, pipeline=None, subtitle_widget=None):
        super().__init__()
        self.tray_manager = tray_manager
        self.pipeline = pipeline
        self.subtitle_widget = subtitle_widget

        self._speaker_order: list[int] = []
        self._chips: dict[int, QLabel] = {}

        self.setObjectName("mainWindow")
        self.setWindowTitle(tr("app_title"))
        self.setFixedSize(430, 540)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        icon_path = app_dir() / "assets" / "vocis_32.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()

        # 字幕信号同样用于维护说话人图例（Qt 信号可多路连接）
        if subtitle_widget is not None:
            subtitle_widget.subtitle_signal.connect(self._on_subtitle)
            subtitle_widget._stream_signal.connect(self._on_stream)

        self.retranslate()
        self.sync_language()
        self.refresh_status()

    # ── 构建 ──────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(12)

        outer.addLayout(self._build_header())

        self._config_title = QLabel("")
        self._config_title.setObjectName("sectionTitle")
        outer.addWidget(self._config_title)

        outer.addWidget(self._build_info_card())
        outer.addWidget(self._build_speaker_card())
        outer.addStretch(1)

        self._shortcuts_hint = QLabel("")
        self._shortcuts_hint.setObjectName("hint")
        self._shortcuts_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._shortcuts_hint)

        self._toggle_btn = QPushButton("")
        self._toggle_btn.setObjectName("primary")
        self._toggle_btn.setFixedHeight(44)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle)
        outer.addWidget(self._toggle_btn)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._settings_btn = QPushButton("")
        self._log_btn = QPushButton("")
        self._quit_btn = QPushButton("")
        for btn in (self._settings_btn, self._log_btn, self._quit_btn):
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(btn, 1)
        self._settings_btn.clicked.connect(self._open_settings)
        self._log_btn.clicked.connect(self._open_log)
        self._quit_btn.clicked.connect(self._quit)
        outer.addLayout(actions)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self._version_label = QLabel("")
        self._version_label.setObjectName("hint")
        footer.addWidget(self._version_label)
        outer.addLayout(footer)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        logo = QLabel()
        logo.setFixedSize(42, 42)
        logo_path = app_dir() / "assets" / "vocis_64.png"
        if logo_path.exists():
            pm = QPixmap(str(logo_path)).scaled(
                42, 42, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pm)
        row.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("")
        self._title.setObjectName("appTitle")
        self._tagline = QLabel("")
        self._tagline.setObjectName("tagline")
        titles.addWidget(self._title)
        titles.addWidget(self._tagline)
        row.addLayout(titles)
        row.addStretch(1)

        self._status_chip = QFrame()
        self._status_chip.setObjectName("statusChip")
        self._status_chip.setFixedHeight(28)
        chip_lay = QHBoxLayout(self._status_chip)
        chip_lay.setContentsMargins(10, 0, 12, 0)
        chip_lay.setSpacing(7)

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._dot_glow = QGraphicsDropShadowEffect(self._status_dot)
        self._dot_glow.setBlurRadius(14)
        self._dot_glow.setOffset(0, 0)
        self._status_dot.setGraphicsEffect(self._dot_glow)

        self._status_label = QLabel("")
        self._status_label.setObjectName("statusText")
        chip_lay.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_lay.addWidget(self._status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._status_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_info_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self._key_translator = QLabel("")
        self._key_asr = QLabel("")
        self._key_speakers = QLabel("")
        self._key_lang = QLabel("")
        for lbl in (self._key_translator, self._key_asr, self._key_speakers, self._key_lang):
            lbl.setObjectName("keyLabel")

        self._val_translator = QLabel("")
        self._val_asr = QLabel("")
        self._val_speakers = QLabel("")
        for lbl in (self._val_translator, self._val_asr, self._val_speakers):
            lbl.setObjectName("valueLabel")
            lbl.setFixedWidth(260)

        self._lang_combo = ThemedComboBox()
        self._lang_combo.setFixedHeight(30)
        self._lang_combo.setFixedWidth(260)
        for name in (tr("auto"), tr("chinese_zh"), tr("english_en"), tr("japanese_ja")):
            self._lang_combo.addItem(name)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)

        grid.addWidget(self._key_translator, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self._val_translator, 0, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self._key_asr, 1, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self._val_asr, 1, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self._key_speakers, 2, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self._val_speakers, 2, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self._key_lang, 3, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._lang_combo, 3, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(grid)
        return card

    def _build_speaker_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        self._speaker_title = QLabel("")
        self._speaker_title.setObjectName("sectionTitle")
        self._reset_btn = QPushButton("")
        self._reset_btn.setObjectName("link")
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.clicked.connect(self._reset_speakers)
        head.addWidget(self._speaker_title)
        head.addStretch(1)
        head.addWidget(self._reset_btn)
        lay.addLayout(head)

        self._speaker_empty = QLabel("")
        self._speaker_empty.setObjectName("hint")
        lay.addWidget(self._speaker_empty)

        self._chips_grid = QGridLayout()
        self._chips_grid.setHorizontalSpacing(6)
        self._chips_grid.setVerticalSpacing(6)
        self._chips_grid.setColumnStretch(3, 1)
        lay.addLayout(self._chips_grid)

        self._speaker_hint = QLabel("")
        self._speaker_hint.setObjectName("hint")
        lay.addWidget(self._speaker_hint)
        return card

    # ── 对外 ──────────────────────────────────────────

    def retranslate(self):
        """语言切换后刷新界面文案。"""
        self.setWindowTitle(tr("app_title"))
        self._title.setText(tr("app_title"))
        self._tagline.setText(tr("tagline"))
        self._config_title.setText(tr("section_config"))
        self._key_translator.setText(tr("info_translator"))
        self._key_asr.setText(tr("info_asr"))
        self._key_speakers.setText(tr("info_speakers"))
        self._key_lang.setText(tr("tab_language"))
        self._speaker_title.setText(tr("tab_diarization"))
        self._reset_btn.setText(tr("reset"))
        self._speaker_empty.setText(tr("speaker_empty"))
        self._speaker_hint.setText(tr("speaker_auto_hint"))
        self._settings_btn.setText(tr("settings"))
        self._log_btn.setText(tr("view_log"))
        self._quit_btn.setText(tr("quit"))
        self._shortcuts_hint.setText(tr("shortcuts_hint"))

        self._lang_combo.blockSignals(True)
        names = [tr("auto"), tr("chinese_zh"), tr("english_en"), tr("japanese_ja")]
        for i, name in enumerate(names):
            if self._lang_combo.count() > i:
                self._lang_combo.setItemText(i, name)
        self._lang_combo.blockSignals(False)

        for index in self._speaker_order:
            self._style_chip(self._chips[index], index)

        try:
            from importlib.metadata import version as pkg_version
            ver = pkg_version("vocis")
        except Exception:
            ver = "0.5.0"
        self._version_label.setText(tr("version", version=ver))
        self.refresh_status()

    def refresh_status(self):
        """根据 pipeline / 配置刷新状态、当前配置与按钮文案。"""
        paused = bool(self.pipeline is not None and self.pipeline.is_paused)
        self._set_status(paused)

        cfg = get_config()
        lang = current_language()
        zh = lang == "zh"

        tp = TRANSLATION_PRESETS.get(cfg.translator.provider) or translation_preset(
            cfg.translator.provider
        )
        tp_name = tp.get("name_zh" if zh else "name") or cfg.translator.provider
        self._set_info(
            self._val_translator,
            "%s · %s" % (tp_name, cfg.translator.model or tr("not_set")),
        )

        if cfg.asr.is_local:
            ap = LOCAL_ASR_BACKENDS.get(cfg.asr.backend, {})
            ap_name = {
                "whisper": "Whisper",
                "sherpa": "Sherpa",
                "mock": "Mock",
            }.get(cfg.asr.backend) or ap.get("name") or cfg.asr.backend
            if cfg.asr.backend == "whisper":
                detail = cfg.asr.whisper_model or "base"
            elif cfg.asr.backend == "sherpa":
                detail = Path(cfg.asr.sherpa_model_path or "").name or "sherpa"
            else:
                detail = "Mock"
        else:
            ap = ASR_PRESETS.get(cfg.asr.backend) or asr_preset(cfg.asr.backend)
            ap_name = ap.get("name_zh" if zh else "name") or cfg.asr.backend
            detail = cfg.asr.model or tr("not_set")
        self._set_info(self._val_asr, "%s · %s" % (ap_name, detail))

        if cfg.diarization.enabled:
            self._set_info(
                self._val_speakers,
                tr(
                    "speaker_status_on",
                    backend=cfg.diarization.backend,
                    n=len(self._speaker_order),
                ),
            )
        else:
            self._set_info(self._val_speakers, tr("speaker_off"))

        self._reset_btn.setEnabled(bool(self._speaker_order))

    def sync_language(self):
        """从当前配置同步语言下拉框。"""
        lang = self.pipeline.current_language if self.pipeline else get_config().asr.language
        if lang not in LANGS:
            return
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentIndex(LANGS.index(lang))
        self._lang_combo.blockSignals(False)

    # ── 内部 ──────────────────────────────────────────

    @staticmethod
    def _set_info(label: QLabel, text: str):
        """单行显示当前配置，过长时省略并保留完整 tooltip。"""
        label.ensurePolished()
        label.setToolTip(text)
        label.setText(
            label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, label.width() or 260)
        )

    def _set_status(self, paused: bool):
        state = "paused" if paused else "running"
        if self._status_chip.property("state") != state:
            self._status_chip.setProperty("state", state)
            style = self._status_chip.style()
            style.unpolish(self._status_chip)
            style.polish(self._status_chip)
        color = "#fbbf24" if paused else "#34d399"
        self._status_dot.setStyleSheet(
            "background-color: %s; border-radius: 4px;" % color
        )
        glow = QColor(color)
        glow.setAlpha(170)
        self._dot_glow.setColor(glow)
        self._status_label.setText(tr("paused") if paused else tr("running"))
        self._status_label.setStyleSheet("color: %s;" % color)
        self._toggle_btn.setText(tr("resume") if paused else tr("pause"))

    def _style_chip(self, chip: QLabel, index: int):
        color = speaker_color(index - 1)
        text = tr("speaker_n", n=index)
        chip.setText(text)
        chip.setStyleSheet(
            "background-color: %s; color: #08111a; border-radius: 11px; "
            "padding: 1px 9px; font-size: 11px; font-weight: 600;" % color
        )
        fm = QFontMetrics(_font(11, bold=True))
        chip.setFixedWidth(fm.horizontalAdvance(text) + 22)

    def _note_speaker(self, speaker):
        if speaker is None:
            return
        try:
            index = int(getattr(speaker, "index", 0) or 0)
        except (TypeError, ValueError):
            return
        if index <= 0 or index in self._chips:
            return
        chip = QLabel()
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setFixedHeight(22)
        self._style_chip(chip, index)
        pos = len(self._speaker_order)
        self._chips_grid.addWidget(chip, pos // 3, pos % 3)
        self._speaker_order.append(index)
        self._chips[index] = chip
        self._speaker_empty.hide()
        self._reset_btn.setEnabled(True)
        self.refresh_status()

    def _on_subtitle(self, _original, _translation, speaker):
        self._note_speaker(speaker)

    def _on_stream(self, _original, _translation, _is_final, speaker):
        self._note_speaker(speaker)

    def _reset_speakers(self):
        for chip in self._chips.values():
            self._chips_grid.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()
        self._speaker_order.clear()
        self._speaker_empty.show()
        self._reset_btn.setEnabled(False)
        if self.pipeline:
            try:
                self.pipeline.reset_context()
                logger.info("Speaker clustering reset by user")
            except Exception:
                logger.exception("Failed to reset speaker clustering")
        self.refresh_status()

    def _on_lang_changed(self, idx: int):
        if 0 <= idx < len(LANGS) and self.pipeline:
            self.pipeline.set_language(LANGS[idx])
            logger.info("Language switched to %s", LANGS[idx])

    def _toggle(self):
        if self.tray_manager:
            self.tray_manager._toggle()
        self.refresh_status()

    def _open_settings(self):
        from gui.settings import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            if self.subtitle_widget:
                self.subtitle_widget.apply_settings()
            if self.pipeline:
                self.pipeline.apply_config()
            if self.tray_manager:
                self.tray_manager.retranslate()
            else:
                self.retranslate()
            self.sync_language()
            self.refresh_status()

    def _open_log(self):
        import subprocess
        import sys
        log_path = app_dir() / "logs" / "vocis.log"
        if log_path.exists():
            if sys.platform == "win32":
                subprocess.Popen(["notepad", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])

    def _quit(self):
        if self.tray_manager:
            self.tray_manager._quit()
        else:
            QApplication.instance().quit()

    def closeEvent(self, event):
        """关闭主窗口时隐藏而非退出，应用驻留托盘。"""
        self.hide()
        event.ignore()
