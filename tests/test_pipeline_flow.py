"""回归测试：普通模式、增量段最终确认、配置切换与生命周期。"""

import asyncio
import threading
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

from backend.diarization.base import Speaker
from backend.pipeline import SubtitlePipeline, _SegmentJob


class FakeASR:
    is_streaming = False

    def __init__(self, results=None, backend="whisper"):
        self.results = list(results or [])
        self.calls = []
        self.backend = backend
        self.closed = 0
        self.stream_started = 0

    async def transcribe_async(self, audio):
        self.calls.append(audio)
        result = self.results.pop(0) if self.results else None
        if isinstance(result, Exception):
            raise result
        return result

    def transcribe(self, audio):
        return asyncio.run(self.transcribe_async(audio))

    def set_language(self, language):
        pass

    def start_stream(self):
        self.stream_started += 1

    def close(self):
        self.closed += 1


class FakeTranslator:
    def __init__(self, prefix="TR:"):
        self.prefix = prefix
        self.calls = []
        self.closed = 0

    async def translate_async(self, text):
        self.calls.append(text)
        await asyncio.sleep(0)
        return self.prefix + text

    async def translate_stream_async(self, text):
        self.calls.append(text)
        yield self.prefix + text

    def reset_context(self):
        pass

    async def close_async(self):
        self.closed += 1

    def close(self):
        self.closed += 1


def base_pipeline():
    p = SubtitlePipeline.__new__(SubtitlePipeline)
    p.asr = FakeASR()
    p.translator = FakeTranslator()
    p.diarizer = None
    p._on_subtitle = None
    p._on_subtitle_stream = None
    p._buffer_lock = threading.Lock()
    p._segment_lock = threading.Lock()
    p._rolling_audio = bytearray()
    p._diar_audio = bytearray()
    p._segment_jobs = deque()
    p._segment_speaker = None
    p._last_text = ""
    p._confirmed_sentences = []
    p._confirmed_trans = ""
    p._residual = ""
    p._segment_end = threading.Event()
    p._current_lang = None
    p._current_lang_prob = 0.0
    p._skip_translate = False
    p._paused = threading.Event()
    p._paused.set()
    p._running = threading.Event()
    p._running.set()
    p._asr_streaming = False
    p._incremental_max_seconds = 5.0
    p._incremental_interval = 0.1
    p._stream_sentence_chars = 8
    p._retired = []
    p._tasks = []
    p._loop = None
    p._stopping = False
    p._stop_done = False
    return p


def speech_audio(seconds=1.0):
    # 普通噪声（非静音），确保通过 _audio_has_speech 的门禁
    import numpy as np

    rng = np.random.default_rng(0)
    data = (rng.normal(0, 0.1, int(16000 * seconds)) * 32767).astype(np.int16)
    return data.tobytes()


def fake_cfg(**asr_overrides):
    asr = SimpleNamespace(
        backend="whisper",
        api_key="key-1",
        base_url="",
        model="",
        whisper_model="tiny",
        whisper_model_path="models/faster-whisper-tiny",
        whisper_device="cpu",
        sherpa_model_path="models/sherpa-streaming-zh-14M",
        language="auto",
        skip_translate_when_same_lang=True,
    )
    for k, v in asr_overrides.items():
        setattr(asr, k, v)
    return SimpleNamespace(
        asr=asr,
        translator=SimpleNamespace(
            provider="deepseek", api_key="tr-key", base_url="https://api.example.com",
            model="deepseek-chat", target_language="中文",
        ),
        diarization=SimpleNamespace(
            enabled=False, backend="sherpa", max_speakers=4,
            threshold=None, min_seconds=0.6, model_path="",
        ),
        incremental_enabled=True,
        incremental_interval=0.1,
        incremental_max_seconds=5.0,
        stream_sentence_chars=8,
    )


# ── 普通模式 ──────────────────────────────────────────

def test_transcribe_segment_unpacks_tuple_and_rejects_empty():
    p = base_pipeline()
    p.asr = FakeASR([(" hello ", "en", 0.9), ("   ", "en", 1.0), None])
    assert asyncio.run(p._transcribe_segment(b"x")) == ("hello", "en", 0.9)
    assert asyncio.run(p._transcribe_segment(b"x")) is None
    assert asyncio.run(p._transcribe_segment(b"x")) is None


def test_transcribe_segment_accepts_none_language():
    p = base_pipeline()
    p.asr = FakeASR([("你好", None, 0.0)])
    assert asyncio.run(p._transcribe_segment(b"x")) == ("你好", None, 0.0)


def test_queue_translation_carries_skip_flag_and_plain_text():
    p = base_pipeline()
    p._translate_queue = asyncio.Queue()
    cfg = fake_cfg()
    with patch("backend.pipeline.get_config", return_value=cfg):
        p._queue_translation("hi", "en", 0.99, None, "normal")
        p._queue_translation("你好", "zh", 0.99, None, "normal")
    first = p._translate_queue.get_nowait()
    second = p._translate_queue.get_nowait()
    assert first == ("normal", "hi", None, False)
    assert second == ("normal", "你好", None, True)  # zh == 中文目标
    assert isinstance(first[1], str)


def test_asr_worker_never_enqueues_raw_tuple():
    p = base_pipeline()
    p.asr = FakeASR([("hello", "en", 0.9)])
    p.translator = FakeTranslator()

    class FakeVad:
        def flush(self):
            return []

    p.vad = FakeVad()

    async def run():
        p._asr_queue = asyncio.Queue()
        p._translate_queue = asyncio.Queue()
        p._asr_queue.put_nowait(b"segment")
        p._asr_queue.put_nowait(None)
        await p._asr_worker()

    asyncio.run(run())
    item = p._translate_queue.get_nowait()
    assert item is not None
    task_type, text, speaker, skip = item
    assert task_type == "normal"
    assert text == "hello"
    assert isinstance(text, str)  # 修复前这里是整个元组
    assert skip is False


def test_short_segment_is_finalized_before_first_periodic_tick():
    p = base_pipeline()
    p.asr = FakeASR([("嗨", "zh", 0.9)])
    p.translator = FakeTranslator()
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(audio=speech_audio(0.3))))
    assert got == [("嗨", "TR:嗨", True, None)]


def test_handle_skip_item_keeps_original_text():
    p = base_pipeline()
    p.translator = FakeTranslator()
    got = []
    p._on_subtitle = lambda *args: got.append(args)
    asyncio.run(p._handle_translate_item(("normal", "你好", Speaker(1), True)))
    assert got == [("你好", "", Speaker(1))]
    assert p.translator.calls == []


def test_handle_item_translation_failure_shows_original():
    p = base_pipeline()

    class BrokenTranslator(FakeTranslator):
        async def translate_async(self, text):
            return None

    p.translator = BrokenTranslator()
    got = []
    p._on_subtitle = lambda *args: got.append(args)
    asyncio.run(p._handle_translate_item(("flush", "hello", None, False)))
    assert got == [("hello", "", None)]


# ── 增量段最终确认 ────────────────────────────────────

def test_non_streaming_short_segment_gets_final_subtitle():
    p = base_pipeline()
    p.asr = FakeASR([("短句", "zh", 0.9)])
    p.translator = FakeTranslator()
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(audio=speech_audio())))
    assert got == [("短句", "TR:短句", True, None)]
    assert p.asr.calls == [speech_audio()]


def test_streaming_final_extends_partial_without_duplicate_translation():
    p = base_pipeline()
    p._asr_streaming = True
    p.translator = FakeTranslator()
    p._last_text = "hello"
    p._residual = "hello"
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(final_text="hello world")))
    assert p.translator.calls == ["hello world"]
    assert got == [("hello world", "TR:hello world", True, None)]


def test_streaming_final_correction_does_not_repeat_confirmed_text():
    p = base_pipeline()
    p._asr_streaming = True
    p.translator = FakeTranslator()
    p._confirmed_sentences = ["你好。"]
    p._confirmed_trans = "TR:你好。"
    p._last_text = "你好。"
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(final_text="你好。世界")))
    assert p.translator.calls == ["世界"]
    assert got[-1][0] == "你好。世界"
    assert got[-1][2] is True


def test_streaming_final_correction_does_not_duplicate_replaced_chars():
    p = base_pipeline()
    p._asr_streaming = True
    p.translator = FakeTranslator()
    p._confirmed_sentences = ["hello wor"]
    p._confirmed_trans = "TR:hello wor"
    p._last_text = "hello wrold"
    p._residual = "wrold"
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(final_text="hello world")))
    assert p.translator.calls == ["ld"]
    assert got[-1][0] == "hello world"


def test_complete_sentence_without_residual_still_emits_final_frame():
    p = base_pipeline()
    p._asr_streaming = True
    p.translator = FakeTranslator()
    p._confirmed_sentences = ["完整句子。"]
    p._confirmed_trans = "TR:完整句子。"
    p._last_text = "完整句子。"
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(final_text="完整句子。")))
    assert got == [("完整句子。", "TR:完整句子。", True, None)]


def test_final_asr_failure_keeps_partial_text():
    p = base_pipeline()
    p.asr = FakeASR([RuntimeError("boom")])
    p.translator = FakeTranslator()
    p._last_text = "partial"
    p._residual = "partial"
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    asyncio.run(p._finalize_segment(_SegmentJob(audio=speech_audio())))
    assert got == [("partial", "TR:partial", True, None)]


def test_silent_segment_emits_nothing():
    p = base_pipeline()
    p.asr = FakeASR([("幻觉", "zh", 0.9)])
    p.translator = FakeTranslator()
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)
    silent = b"\x00\x00" * 16000

    asyncio.run(p._finalize_segment(_SegmentJob(audio=silent)))
    assert got == []
    assert p.asr.calls == []


def test_two_segments_are_finalized_in_order_with_slow_translation():
    p = base_pipeline()
    p._asr_streaming = True
    p.translator = FakeTranslator()
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)

    class SlowTranslator(FakeTranslator):
        async def translate_async(self, text):
            await asyncio.sleep(0.03)
            return "TR:" + text

    p.translator = SlowTranslator()
    with p._segment_lock:
        p._segment_jobs.append(_SegmentJob(final_text="one"))
        p._segment_jobs.append(_SegmentJob(final_text="two"))
    p._segment_end.set()

    asyncio.run(p._drain_segment_jobs())
    finals = [e for e in got if e[2]]
    assert [f[0] for f in finals] == ["one", "two"]
    assert len(finals) == 2
    assert p._segment_jobs == deque()
    assert not p._segment_end.is_set()


def test_rolling_buffer_is_bounded():
    p = base_pipeline()
    p._incremental_max_seconds = 1.0
    p._extend_rolling_audio(b"\x01\x00" * 100000)
    assert len(p._snapshot_rolling_audio()) <= int(1.0 * 16000 * 2)


# ── 配置切换 ──────────────────────────────────────────

def test_asr_signature_covers_key_paths_and_device():
    p = base_pipeline()
    base = p._make_asr_signature(fake_cfg())
    for overrides in (
        {"api_key": "key-2"},
        {"whisper_model_path": "models/faster-whisper-base"},
        {"whisper_device": "cuda"},
        {"sherpa_model_path": "models/other"},
        {"base_url": "https://new"},
        {"model": "new-model"},
    ):
        assert p._make_asr_signature(fake_cfg(**overrides)) != base


def test_apply_config_keeps_old_asr_when_rebuild_fails():
    p = base_pipeline()
    old_asr = FakeASR([])
    old_translator = FakeTranslator()
    p.asr = old_asr
    p.translator = old_translator
    p.diarizer = None
    cfg = fake_cfg()
    p._asr_signature = p._make_asr_signature(cfg)
    p._diar_signature = p._make_diar_signature(cfg)
    new_translator = FakeTranslator()
    changed = fake_cfg(api_key="key-2")

    with (
        patch("backend.pipeline.create_translator", return_value=new_translator),
        patch("backend.pipeline.create_asr", side_effect=RuntimeError("no model")),
    ):
        ok = asyncio.run(p._async_apply_config(changed, live=False))

    assert ok is False
    assert p.asr is old_asr
    assert p.translator is new_translator
    assert old_translator.closed == 1
    assert p._asr_signature != p._make_asr_signature(changed)


def test_apply_config_rejects_silent_backend_fallback():
    p = base_pipeline()
    old_asr = FakeASR([])
    p.asr = old_asr
    p.translator = FakeTranslator()
    p.diarizer = None
    cfg = fake_cfg()
    p._asr_signature = p._make_asr_signature(cfg)
    p._diar_signature = p._make_diar_signature(cfg)
    changed = fake_cfg(api_key="key-2")
    fallback = FakeASR([], backend="mimo")

    with (
        patch("backend.pipeline.create_translator", return_value=FakeTranslator()),
        patch("backend.pipeline.create_asr", return_value=fallback),
    ):
        ok = asyncio.run(p._async_apply_config(changed, live=False))

    assert ok is False
    assert p.asr is old_asr
    assert fallback.closed == 1


def test_apply_config_swaps_engine_and_retires_old_until_stop():
    p = base_pipeline()
    old_asr = FakeASR([])
    p.asr = old_asr
    p.translator = FakeTranslator()
    p.diarizer = None
    cfg = fake_cfg()
    p._asr_signature = p._make_asr_signature(cfg)
    p._diar_signature = p._make_diar_signature(cfg)
    changed = fake_cfg(api_key="key-2")
    new_asr = FakeASR([], backend="whisper")

    with (
        patch("backend.pipeline.create_translator", return_value=FakeTranslator()),
        patch("backend.pipeline.create_asr", return_value=new_asr),
    ):
        ok = asyncio.run(p._async_apply_config(changed, live=True))

    assert ok is True
    assert p.asr is new_asr
    assert old_asr in p._retired
    assert old_asr.closed == 0  # 不在可能仍在推理时关闭
    p._close_retired()
    assert old_asr.closed == 1
