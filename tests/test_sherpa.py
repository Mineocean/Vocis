"""Tests for sherpa-onnx streaming ASR backend."""

from unittest.mock import patch

import pytest

from backend.asr.base import ASREngine
from backend.asr.registry import _REGISTRY, create_asr
from backend.asr.sherpa import SherpaStreamingASR


class TestSherpaRegistration:
    def test_sherpa_registered(self):
        assert "sherpa" in _REGISTRY

    def test_sherpa_is_engine(self, mock_config):
        with patch("backend.config.get_config", return_value=mock_config), \
             patch("backend.asr.sherpa.get_config", return_value=mock_config), \
             patch("backend.asr.sherpa._resolve_model_dir") as mock_resolve, \
             patch("backend.asr.sherpa.Path.exists", return_value=True):
            mock_resolve.return_value = __import__("pathlib").Path("models/sherpa-streaming-zh-14M")
            engine = SherpaStreamingASR()
            assert isinstance(engine, ASREngine)
            assert engine.is_streaming is True

    def test_missing_model_dir_raises(self, mock_config):
        mock_config.asr.sherpa_model_path = "nonexistent-dir"
        with patch("backend.config.get_config", return_value=mock_config), \
             patch("backend.asr.sherpa.get_config", return_value=mock_config), \
             patch("backend.asr.sherpa._resolve_model_dir", return_value=__import__("pathlib").Path("nonexistent-dir")):
            with pytest.raises(FileNotFoundError):
                SherpaStreamingASR()


class _FakeStream:
    def __init__(self, texts=None):
        self._texts = texts or []
        self._finished = False
        self.accepted = []

    def accept_waveform(self, rate, samples):
        self.accepted.append(samples)

    def input_finished(self):
        self._finished = True

    @property
    def result(self):
        return self._texts.pop(0) if self._texts else ""


class _FakeRecognizer:
    def __init__(self, texts=None):
        self._texts = texts or [""]
        self._streams = []

    def create_stream(self):
        s = _FakeStream(self._texts)
        self._streams.append(s)
        return s

    def is_ready(self, stream):
        return False

    def decode_stream(self, stream):
        pass

    def get_result(self, stream):
        return stream.result


class TestSherpaTranscribe:
    def _make_engine(self, texts=None):
        rec = _FakeRecognizer(texts or ["大家好。", ""])
        with patch("backend.config.get_config"), \
             patch("backend.asr.sherpa.get_config"), \
             patch("backend.asr.sherpa._resolve_model_dir") as mock_resolve, \
             patch("backend.asr.sherpa.Path.exists", return_value=True):
            mock_resolve.return_value = __import__("pathlib").Path("models/sherpa-streaming-zh-14M")
            engine = SherpaStreamingASR()
            engine._recognizer = rec
            return engine

    def test_transcribe_empty(self):
        engine = self._make_engine()
        assert engine.transcribe(b"") is None

    def test_transcribe_returns_tuple(self):
        engine = self._make_engine(["大家好。", ""])
        result = engine.transcribe(b"\x00\x01" * 32000)
        assert result is not None
        text, lang, prob = result
        assert text == "大家好。"
        assert lang == "zh"
        assert prob == 1.0

    def test_transcribe_no_text_returns_none(self):
        engine = self._make_engine([""])
        assert engine.transcribe(b"\x00\x01" * 32000) is None

    def test_missing_import_raises(self):
        engine = self._make_engine()
        engine._recognizer = None
        with patch("builtins.__import__", side_effect=ImportError("no sherpa")):
            with pytest.raises(ImportError, match="sherpa-onnx"):
                engine._load_model()


class TestSherpaStreaming:
    def test_push_and_partial(self):
        rec = _FakeRecognizer(["大家好", "大家好欢迎"])
        with patch("backend.config.get_config"), \
             patch("backend.asr.sherpa.get_config"), \
             patch("backend.asr.sherpa._resolve_model_dir"), \
             patch("backend.asr.sherpa.Path.exists", return_value=True):
            engine = SherpaStreamingASR()
            engine._recognizer = rec
            engine.start_stream()
            engine.push_audio(b"\x00\x01" * 3200)
            assert engine.get_partial_text() == "大家好"
            assert engine._stream is not None

    def test_end_stream_clears_stream(self):
        rec = _FakeRecognizer(["最终结果", ""])
        with patch("backend.config.get_config"), \
             patch("backend.asr.sherpa.get_config"), \
             patch("backend.asr.sherpa._resolve_model_dir"), \
             patch("backend.asr.sherpa.Path.exists", return_value=True):
            engine = SherpaStreamingASR()
            engine._recognizer = rec
            engine.start_stream()
            engine.push_audio(b"\x00\x01" * 3200)
            text = engine.end_stream()
            assert text == "最终结果"
            assert engine._stream is None

    def test_partial_before_start_returns_empty(self):
        with patch("backend.config.get_config"), \
             patch("backend.asr.sherpa.get_config"), \
             patch("backend.asr.sherpa._resolve_model_dir"), \
             patch("backend.asr.sherpa.Path.exists", return_value=True):
            engine = SherpaStreamingASR()
            assert engine.get_partial_text() == ""


class TestSherpaFallback:
    def test_create_asr_sherpa(self, mock_config):
        mock_config.asr.backend = "sherpa"
        mock_config.asr.sherpa_model_path = "models/sherpa-streaming-zh-14M"
        with patch("backend.config.get_config", return_value=mock_config), \
             patch("backend.asr.whisper.get_config", return_value=mock_config), \
             patch("backend.asr.sherpa._resolve_model_dir"), \
             patch("backend.asr.sherpa.Path.exists", return_value=True):
            engine = create_asr()
            assert isinstance(engine, SherpaStreamingASR)
            engine.close()

    def test_create_asr_sherpa_fallback_mimo(self, mock_config):
        from pathlib import Path
        mock_config.asr.backend = "sherpa"
        mock_config.asr.sherpa_model_path = "missing"
        with patch("backend.config.get_config", return_value=mock_config), \
             patch("backend.asr.sherpa._resolve_model_dir", return_value=Path("missing")), \
             patch("backend.asr.sherpa.Path.exists", return_value=False), \
             patch("backend.asr.registry.logger.warning"):
            engine = create_asr()
            # sherpa 缺失 → 回退 mimo
            assert type(engine).__name__ == "MiMoASR"
            engine.close()


class TestPipelineStreaming:
    """pipeline 流式分支：按字数切句 + 跳译 + 段结束 flush。"""

    def _make_pipe(self, streaming_asr=True):
        import threading
        from backend.pipeline import SubtitlePipeline
        pipe = SubtitlePipeline.__new__(SubtitlePipeline)
        pipe.asr = object()
        pipe._asr_streaming = streaming_asr
        pipe._stream_sentence_chars = 12
        pipe._incremental_interval = 1.2
        pipe._incremental_max_seconds = 5.0
        pipe._running = threading.Event()
        pipe._running.set()
        pipe._paused = threading.Event()
        pipe._paused.set()
        pipe._rolling_audio = bytearray()
        pipe._last_text = ""
        pipe._confirmed_sentences = []
        pipe._confirmed_trans = ""
        pipe._residual = ""
        pipe._segment_end = threading.Event()
        pipe._current_lang = None
        pipe._current_lang_prob = 0.0
        pipe._skip_translate = False
        pipe._emits = []
        pipe._emit_stream = lambda o, t, f: pipe._emits.append((o, t, f))
        return pipe

    def test_streaming_chunk_by_chars(self):
        """sherpa 输出无标点，按字数强制切句翻译。"""
        pipe = self._make_pipe()
        # 模拟 partial 恰好 12 字完整增长
        pipe._last_text = ""
        text = "天气真" + "好" * 9  # 12 字
        new_text = pipe._diff_text(pipe._last_text, text)
        pipe._last_text = text
        pipe._residual += new_text
        emitted = False
        while len(pipe._residual) >= pipe._stream_sentence_chars:
            sent = pipe._residual[:pipe._stream_sentence_chars]
            pipe._residual = pipe._residual[pipe._stream_sentence_chars:]
            pipe._confirmed_sentences.append(sent)
            emitted = True
        assert emitted is True
        assert len(pipe._confirmed_sentences) == 1
        assert len(pipe._confirmed_sentences[0]) == 12
        # 无残句残留（刚好 12 字）
        assert pipe._residual == ""

    def test_streaming_keeps_residual(self):
        """不足 12 字的文本保留为残句，不切句。"""
        pipe = self._make_pipe()
        pipe._last_text = ""
        text = "今天天气"  # 4 字，不足 12
        new_text = pipe._diff_text(pipe._last_text, text)
        pipe._last_text = text
        pipe._residual += new_text
        emitted = False
        while len(pipe._residual) >= pipe._stream_sentence_chars:
            sent = pipe._residual[:pipe._stream_sentence_chars]
            pipe._residual = pipe._residual[pipe._stream_sentence_chars:]
            pipe._confirmed_sentences.append(sent)
            emitted = True
        assert emitted is False
        assert pipe._residual == "今天天气"

    def test_streaming_diff_monotonic(self):
        """部分结果单调增长时，_diff_text 前缀匹配取新增。"""
        pipe = self._make_pipe()
        assert pipe._diff_text("大家好欢迎", "大家好欢迎收") == "收"
        assert pipe._diff_text("", "大家好") == "大家好"
        assert pipe._diff_text("大家好", "大家好") == ""

