"""字幕回调携带说话人标签。"""

import asyncio
import threading

from backend.diarization.base import Speaker
from backend.pipeline import SubtitlePipeline


def _bare_pipeline():
    p = SubtitlePipeline.__new__(SubtitlePipeline)
    p._on_subtitle = None
    p._on_subtitle_stream = None
    p.diarizer = None
    p._buffer_lock = threading.Lock()
    p._diar_audio = bytearray()
    p._segment_speaker = None
    p._residual = ""
    p._last_text = ""
    p._confirmed_trans = ""
    p._skip_translate = False
    return p


def test_emit_subtitle_forwards_speaker():
    p = _bare_pipeline()
    got = []
    p._on_subtitle = lambda *args: got.append(args)
    p._emit_subtitle("hello", "你好", Speaker(2))
    assert got == [("hello", "你好", Speaker(2))]


def test_emit_stream_forwards_speaker_and_final_flag():
    p = _bare_pipeline()
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)
    p._emit_stream("hello", "你好", True, Speaker(3))
    assert got == [("hello", "你好", True, Speaker(3))]


def test_flush_residual_always_emits_final_frame():
    p = _bare_pipeline()
    got = []
    p._on_subtitle_stream = lambda *args: got.append(args)
    p._residual = "最后一句"
    p._last_text = "最后一句"
    p._skip_translate = True  # 跳译模式下译文为空，但原文必须发出
    asyncio.run(p._flush_residual(Speaker(1)))
    assert got == [("最后一句", "", True, Speaker(1))]
    assert p._residual == ""


def test_ensure_segment_speaker_assigns_once():
    p = _bare_pipeline()
    calls = []

    class FakeDiarizer:
        async def assign_async(self, audio):
            calls.append(len(audio))
            return Speaker(2)

    p.diarizer = FakeDiarizer()
    p._diar_audio = bytearray(b"\x00\x00" * 16000)
    assert asyncio.run(p._ensure_segment_speaker()) == Speaker(2)
    # 段内第二次调用不再重复做嵌入
    assert asyncio.run(p._ensure_segment_speaker()) == Speaker(2)
    assert len(calls) == 1


def test_ensure_segment_speaker_skips_short_audio():
    p = _bare_pipeline()

    class BoomDiarizer:
        async def assign_async(self, audio):
            raise AssertionError("should not be called")

    p.diarizer = BoomDiarizer()
    p._diar_audio = bytearray(b"\x00\x00" * 1000)
    assert asyncio.run(p._ensure_segment_speaker()) is None


def test_ensure_segment_speaker_disabled():
    p = _bare_pipeline()
    p._diar_audio = bytearray(b"\x00\x00" * 16000)
    assert asyncio.run(p._ensure_segment_speaker()) is None
