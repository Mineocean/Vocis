"""GUI wiring smoke tests (offscreen Qt).

These catch the classic integration break: subtitle signal arity, missing
i18n keys, or a dialog that cannot be constructed. They do not assert pixels.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from backend.diarization.base import Speaker  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def overlay(qapp):
    from gui.subtitle_widget import SubtitleWidget

    widget = SubtitleWidget()
    yield widget
    widget.close()


def test_i18n_has_both_languages(qapp):
    from gui import i18n

    assert i18n._ZH.keys() == i18n._EN.keys()
    assert i18n._ZH["app_title"]
    assert i18n._EN["app_title"]


def test_overlay_renders_speaker_and_texts(overlay):
    from gui.i18n import tr

    overlay.show_subtitle("你好", "Hello", Speaker(2))
    assert overlay._original == "你好"
    assert overlay._translation == "Hello"
    assert overlay._speaker == Speaker(2)
    assert overlay._pill.isVisibleTo(overlay)
    assert tr("speaker_n", n=2) in overlay._pill.text()


def test_overlay_uses_translation_as_primary_text(overlay):
    overlay.apply_settings()
    overlay.show_subtitle("原文", "Translation", Speaker(1))
    assert overlay._trans.font().pixelSize() > overlay._orig.font().pixelSize()
    # 字号真的生效（QSS 全局 13px 不应覆盖 label 内联字号）
    overlay._orig.setStyleSheet("background: transparent; font-size: 13px;")
    config = __import__("backend.config", fromlist=["get_config"]).get_config()
    if int(config.display.font_size) != 13:
        assert overlay._trans.font().pixelSize() == int(config.display.font_size)


def test_overlay_hides_pill_without_speaker(overlay):
    overlay.show_subtitle("只有原文", "", None)
    assert overlay._speaker is None
    assert not overlay._pill.isVisibleTo(overlay)
    assert not overlay._trans.isVisibleTo(overlay)


def test_stream_signal_arity_and_coalescing(overlay):
    overlay.subtitle_signal.emit("原始", "译文", Speaker(1))
    assert overlay._original == "原始"

    overlay._on_stream("流式原文", "流式", False, Speaker(3))
    assert overlay._pending is not None  # 合并到 20fps 定时器，不是立即重排
    overlay._on_stream("流式原文", "流式完成", True, Speaker(3))
    assert overlay._pending is None
    assert overlay._translation == "流式完成"


def test_main_window_constructs_and_tracks_speakers(qapp):
    from gui.main_window import MainWindow

    window = MainWindow(pipeline=None, subtitle_widget=None)
    try:
        window._note_speaker(Speaker(1))
        window._note_speaker(Speaker(2))
        window._note_speaker(Speaker(1))  # 重复不新增
        assert window._speaker_order == [1, 2]
        assert set(window._chips) == {1, 2}
        window.retranslate()
        window.refresh_status()
        assert window._val_target.text()  # 主窗口能看到「翻成什么」
        assert window._enable_diar_btn is not None
    finally:
        window.close()


def test_settings_dialog_constructs(qapp):
    from gui.settings import SettingsDialog
    from gui.widgets import ThemedCheckBox

    dialog = SettingsDialog()
    try:
        providers = [dialog._tr_provider.itemData(i) for i in range(dialog._tr_provider.count())]
        assert "deepseek" in providers
        assert "custom" in providers
        assert dialog._diar_backend.count() == 2
        assert dialog._tr_model.currentText()
        assert isinstance(dialog._check_stream, ThemedCheckBox)
    finally:
        dialog.close()


def test_settings_dialog_opens_requested_tab(qapp):
    from gui.settings import SettingsDialog

    dialog = SettingsDialog(initial_tab=2)
    try:
        assert dialog._tabs.currentIndex() == 2
    finally:
        dialog.close()


def test_wizard_blocks_empty_key(qapp):
    from gui.setup_wizard import SetupWizard

    wizard = SetupWizard()
    try:
        wizard._stack.setCurrentIndex(1)
        wizard._provider.setCurrentIndex(
            [wizard._provider.itemData(i) for i in range(wizard._provider.count())].index("deepseek")
        )
        wizard._key.clear()
        wizard._go_next()
        assert wizard._stack.currentIndex() == 1
        assert not wizard._key_err.isHidden()
    finally:
        wizard.close()
