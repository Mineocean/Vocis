"""启动配置刷新、停止流程与不可阻塞的采集队列测试。"""

import queue
import threading
from unittest.mock import patch

import numpy as np

from backend.capture import AudioCapture
from backend.pipeline import SubtitlePipeline
from backend.wasapi_loopback import WasapiLoopbackCapture


def test_load_runtime_config_reloads_env_and_language(monkeypatch):
    import main

    calls = []

    def fake_load_dotenv(path, override=True):
        calls.append(("dotenv", path, override))

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)
    monkeypatch.setattr("backend.config.reload_config", lambda: calls.append(("config",)) or object())
    monkeypatch.setattr("gui.i18n.reload_language", lambda: calls.append(("language",)))

    main._load_runtime_config()

    assert calls[0][0] == "dotenv"
    # 不能覆盖向导/进程内已经应用的配置
    assert calls[0][2] is False
    assert ("config",) in calls
    assert ("language",) in calls
    assert calls.index(("config",)) > 0


def test_capture_stop_does_not_block_when_queue_is_full():
    cap = AudioCapture.__new__(AudioCapture)
    cap.queue = queue.Queue(maxsize=2)
    cap.queue.put_nowait(np.zeros(10, dtype=np.float32))
    cap.queue.put_nowait(np.zeros(10, dtype=np.float32))
    cap._running = threading.Event()
    cap._running.set()
    cap._stream = None
    cap._use_wasapi = False
    cap._enabled = True

    cap.stop()  # 修复前这里会永久阻塞
    assert cap.queue.qsize() <= 2


def test_wasapi_stop_does_not_block_when_queue_is_full():
    cap = WasapiLoopbackCapture(sample_rate=16000)
    cap.queue = queue.Queue(maxsize=2)
    cap.queue.put_nowait(np.zeros(10, dtype=np.float32))
    cap.queue.put_nowait(np.zeros(10, dtype=np.float32))
    cap._running.set()

    cap.stop()
    assert cap.queue.qsize() <= 2


class _FakeASR:
    is_streaming = False
    backend = "whisper"

    async def transcribe_async(self, audio):
        return None

    def transcribe(self, audio):
        return None

    def set_language(self, language):
        pass

    def close(self):
        pass


class _FakeTranslator:
    async def translate_async(self, text):
        return ""

    def reset_context(self):
        pass

    async def close_async(self):
        pass

    def close(self):
        pass


class _FakeVAD:
    def process_chunk(self, chunk):
        return []

    def flush(self):
        return []

    def reset(self):
        pass


class _FakeCapture:
    def __init__(self):
        self.started = False
        self.stopped = 0
        self._enabled = True

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped += 1

    def set_enabled(self, value):
        self._enabled = value

    def read(self, timeout=0.5):
        import time

        time.sleep(0.01)
        return np.zeros(0, dtype=np.float32)


def _build_pipeline():
    with (
        patch("backend.pipeline.AudioCapture", return_value=_FakeCapture()),
        patch("backend.pipeline.VoiceActivityDetector", return_value=_FakeVAD()),
        patch("backend.pipeline.create_asr", return_value=_FakeASR()),
        patch("backend.pipeline.create_translator", return_value=_FakeTranslator()),
        patch("backend.pipeline.create_diarizer", return_value=None),
    ):
        return SubtitlePipeline()


def test_pipeline_stop_is_idempotent_and_finishes():
    pipeline = _build_pipeline()
    assert pipeline.start() is True
    pipeline.stop()
    pipeline.stop()  # 第二次调用必须立即返回
    assert pipeline._stop_done is True
    assert pipeline._loop is None
    assert pipeline._loop_thread is None


def test_pipeline_stop_while_paused_is_bounded():
    pipeline = _build_pipeline()
    assert pipeline.start() is True
    pipeline.pause()
    pipeline.stop()
    assert pipeline._stop_done is True
    assert pipeline._loop is None


def test_start_failure_cleans_capture():
    pipeline = _build_pipeline()

    async def fail_start():
        raise RuntimeError("boom")

    pipeline._async_start = fail_start  # type: ignore[method-assign]
    assert pipeline.start() is False
    assert pipeline.capture.stopped >= 1
    assert pipeline._loop is None
