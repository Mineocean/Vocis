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
    finally:
        window.close()


def test_settings_dialog_constructs(qapp):
    from gui.settings import SettingsDialog

    dialog = SettingsDialog()
    try:
        providers = [dialog._tr_provider.itemData(i) for i in range(dialog._tr_provider.count())]
        assert "deepseek" in providers
        assert "custom" in providers
        assert dialog._diar_backend.count() == 2
        assert dialog._tr_model.currentText()
    finally:
        dialog.close()
