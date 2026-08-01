"""
Main pipeline — Audio capture → VAD → ASR → Translation → GUI.

Async architecture:
  - Audio feeder coroutine reads audio and runs VAD inline
  - ASR worker coroutine transcribes speech to text
  - Translate worker coroutine translates text and emits subtitles
"""

import asyncio
import difflib
import logging
import re
import threading
from collections.abc import Callable

import numpy as np

from .asr import create_asr
from .capture import AudioCapture
from .config import get_config, reload_config
from .translator import DeepSeekTranslator
from .vad import VoiceActivityDetector

logger = logging.getLogger(__name__)

# 句子结束标点（中文/英文），用于增量翻译按句切分
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])")


class SubtitlePipeline:
    """
    Async subtitle pipeline.

    Coroutines: audio_feeder → asr_worker → translate_worker
    """

    def __init__(self):
        self.capture = AudioCapture()
        self.vad = VoiceActivityDetector()
        self.asr = create_asr()
        self.translator = DeepSeekTranslator()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._paused.set()  # Not paused initially

        self._asr_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=10)
        self._translate_queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue(maxsize=5)

        self._on_subtitle: Callable[[str, str], None] | None = None
        self._on_subtitle_stream: Callable[[str, str, bool], None] | None = None

        # Futures for cross-thread communication
        self._tasks: list[asyncio.Task] = []

        self._language = get_config().asr.language

        # ── 增量实时识别（方案 D）状态 ──
        cfg = get_config()
        self.incremental_enabled = cfg.incremental_enabled
        self._incremental_interval = cfg.incremental_interval
        self._incremental_max_seconds = cfg.incremental_max_seconds
        self._rolling_audio: bytearray = bytearray()   # 累积的 int16 PCM（本段）
        self._last_text = ""                            # 上一次 ASR 全文
        self._confirmed_sentences: list[str] = []       # 已翻译的完整句子原文
        self._confirmed_trans = ""                      # 已确认译文（追加式）
        self._residual = ""                             # 当前未完整句子（残句，段结束才翻译）
        self._segment_end = threading.Event()           # VAD 段结束信号

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()

    @property
    def current_language(self) -> str:
        return self._language

    def on_subtitle(self, callback: Callable[[str, str], None]):
        self._on_subtitle = callback

    def on_subtitle_stream(self, callback: Callable[[str, str, bool], None]):
        self._on_subtitle_stream = callback

    def _start_event_loop(self):
        """Run asyncio event loop in a dedicated thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self) -> bool:
        """Start the pipeline."""
        if not self.capture.start():
            return False

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._start_event_loop, daemon=True)
        self._loop_thread.start()

        # Schedule async startup
        future = asyncio.run_coroutine_threadsafe(self._async_start(), self._loop)
        try:
            future.result(timeout=5.0)
        except Exception as e:
            logger.error("Failed to start pipeline: %s", e)
            return False

        logger.info("Pipeline started (async)")
        return True

    async def _async_start(self):
        """Start all coroutines."""
        self._running.set()
        self._paused.set()

        self._tasks = [
            asyncio.create_task(self._audio_feeder(), name="audio_feeder"),
        ]
        if self.incremental_enabled:
            self._tasks.append(
                asyncio.create_task(self._incremental_worker(), name="incremental_worker")
            )
        else:
            self._tasks.append(asyncio.create_task(self._asr_worker(), name="asr_worker"))
            self._tasks.append(asyncio.create_task(self._translate_worker(), name="translate_worker"))
        logger.debug("Async tasks started")

    def stop(self):
        """Stop the pipeline."""
        if self._loop is None:
            return

        self._running.clear()
        self._paused.set()  # Unblock any paused coroutines

        # Signal workers to stop
        try:
            asyncio.run_coroutine_threadsafe(
                self._asr_queue.put(None), self._loop
            ).result(timeout=2.0)
            asyncio.run_coroutine_threadsafe(
                self._translate_queue.put(None), self._loop
            ).result(timeout=2.0)

            # Cancel tasks
            for task in self._tasks:
                self._loop.call_soon_threadsafe(task.cancel)

            # Wait for tasks to finish
            try:
                future = asyncio.run_coroutine_threadsafe(
                    asyncio.gather(*self._tasks, return_exceptions=True), self._loop
                )
                future.result(timeout=5.0)
            except Exception:
                pass
        except Exception:
            pass

        self.capture.stop()
        self.translator.close()
        self.asr.close()

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3.0)

        logger.info("Pipeline stopped")

    def pause(self):
        self._paused.clear()
        self.capture.set_enabled(False)
        logger.info("Pipeline paused")

    def resume(self):
        self._paused.set()
        self.capture.set_enabled(True)
        self.vad.reset()
        self._reset_incremental()
        logger.info("Pipeline resumed")

    def set_language(self, lang: str):
        self._language = lang
        self.asr.set_language(lang)
        logger.info("ASR language: %s", lang)

    def apply_config(self):
        cfg = reload_config()
        self._language = cfg.asr.language
        self.asr.set_language(cfg.asr.language)
        self.translator.target_language = cfg.translator.target_language
        logger.info("Config updated: ASR=%s, target=%s", cfg.asr.language, cfg.translator.target_language)

    def reset_context(self):
        self.translator.reset_context()
        self.vad.reset()
        self._reset_incremental()

    # ── Async coroutines ──────────────────────────────

    async def _audio_feeder(self):
        """Read audio from capture device and feed to VAD processor."""
        logger.debug("Audio feeder started")
        while self._running.is_set():
            await asyncio.to_thread(self._paused.wait)
            try:
                chunk = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.capture.read(timeout=0.5)
                )
                if chunk is None:
                    break
                if len(chunk) == 0:
                    continue

                if self.incremental_enabled:
                    # 方案 D：累积 int16 PCM 到滚动缓冲，供增量 worker 周期识别
                    pcm = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
                    self._rolling_audio.extend(pcm.tobytes())
                    # VAD 仅用于检测段边界（静音结束 → 发段结束信号）
                    if self.vad.process_chunk(chunk):
                        self._segment_end.set()
                else:
                    # 段落模式：VAD 切段后整体送 ASR
                    speech_segments = self.vad.process_chunk(chunk)
                    for segment in speech_segments:
                        try:
                            self._asr_queue.put_nowait(segment)
                        except asyncio.QueueFull:
                            logger.warning("ASR queue full, dropping segment")
            except Exception:
                logger.exception("Audio feeder error")
                await asyncio.sleep(0.5)
        logger.debug("Audio feeder stopped")

    # ── 方案 D：滚动累积 + 文本差分 增量识别 ──────────

    @staticmethod
    def _diff_text(prev: str, curr: str) -> str:
        """返回 curr 相对 prev 的新增文本（字符级差分）。"""
        if not prev:
            return curr
        if curr.startswith(prev):
            return curr[len(prev):]
        # 识别中途修正导致前缀不匹配：退化为字符级 diff 找新增
        sm = difflib.SequenceMatcher(None, prev, curr)
        return "".join(curr[j1:j2] for tag, i1, i2, j1, j2 in sm.get_opcodes()
                       if tag in ("insert", "replace"))

    @staticmethod
    def _split_sentences(text: str) -> tuple[list[str], str]:
        """按句子结束标点切分。

        :return: (完整句子列表, 末尾残句)。残句是还没有结束标点的半句。
        """
        if not text:
            return [], ""
        parts = _SENTENCE_RE.split(text)
        # 最后一段可能是残句（无结束标点）
        last = parts[-1] if parts else ""
        if parts and (not last or not _SENTENCE_RE.search(last)):
            complete = parts[:-1]
        else:
            complete = parts
            last = ""
        return [p for p in complete if p and p.strip()], (last or "")

    def _reset_incremental(self):
        self._rolling_audio.clear()
        self._last_text = ""
        self._confirmed_sentences.clear()
        self._confirmed_trans = ""
        self._residual = ""
        self._segment_end.clear()

    async def _incremental_worker(self):
        """周期性识别滚动音频，差分出新增完整句子并增量翻译。"""
        logger.debug("Incremental worker started")
        while self._running.is_set():
            await asyncio.sleep(self._incremental_interval)
            await asyncio.to_thread(self._paused.wait)
            if not self._running.is_set():
                break

            # 段结束：翻译残句作为最终确认，然后重置本段状态
            if self._segment_end.is_set():
                await self._flush_residual()
                self._reset_incremental()
                continue

            audio = bytes(self._rolling_audio)
            if not audio:
                continue

            # 截断过长的滚动缓冲，避免云端 ASR 处理超时
            max_bytes = int(self._incremental_max_seconds * 16000 * 2)
            if len(audio) > max_bytes:
                audio = audio[-max_bytes:]

            try:
                text = await self.asr.transcribe_async(audio)
            except Exception:
                logger.exception("Incremental ASR error")
                continue
            if not text:
                continue
            text = text.strip()

            new_text = self._diff_text(self._last_text, text)
            self._last_text = text

            # 把新增部分 + 残留残句合并成"待翻译池"
            pool = (self._residual + new_text) if self._residual else new_text
            sentences, residual = self._split_sentences(pool)

            # 用句子级差分找出真正新增的完整句子（避免前缀修正导致的重复）
            new_sentences = self._diff_sentences(self._confirmed_sentences, sentences)
            if new_sentences:
                await self._translate_sentences(new_sentences)
                self._confirmed_sentences = sentences
                self._emit_stream(text, self._confirmed_trans, False)

            self._residual = residual

        logger.debug("Incremental worker stopped")

    @classmethod
    def _diff_sentences(cls, prev: list[str], curr: list[str]) -> list[str]:
        """句子列表差分：返回 curr 中相对 prev 新增的句子。"""
        if not prev:
            return curr
        sm = difflib.SequenceMatcher(None, prev, curr)
        result: list[str] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("insert", "replace"):
                result.extend(curr[j1:j2])
        return result

    async def _translate_sentences(self, sentences: list[str]):
        """逐句翻译完整句子，追加到已确认译文。"""
        for sent in sentences:
            s = sent.strip()
            if not s:
                continue
            try:
                translation = await self.translator.translate_async(s)
            except Exception:
                logger.exception("Incremental translate error")
                continue
            if translation:
                self._confirmed_trans = (
                    (self._confirmed_trans + " " + translation).strip()
                    if self._confirmed_trans
                    else translation
                )

    async def _flush_residual(self):
        """段结束时翻译尚未处理的残句（最终确认）。"""
        residual = self._residual.strip()
        if not residual:
            return
        try:
            translation = await self.translator.translate_async(residual)
        except Exception:
            logger.exception("Incremental flush translate error")
            return
        if translation:
            self._confirmed_trans = (
                (self._confirmed_trans + " " + translation).strip()
                if self._confirmed_trans
                else translation
            )
            self._emit_stream(self._last_text, self._confirmed_trans, True)
        self._residual = ""

    def _emit_stream(self, original: str, translation: str, is_final: bool):
        if self._on_subtitle_stream:
            try:
                self._on_subtitle_stream(original, translation, is_final)
            except Exception:
                logger.exception("Stream subtitle callback error")

    async def _asr_worker(self):
        """Transcribe speech segments to text."""
        logger.debug("ASR worker started")
        while self._running.is_set():
            try:
                segment = await asyncio.wait_for(self._asr_queue.get(), timeout=1.0)
                if segment is None:
                    break

                await asyncio.to_thread(self._paused.wait)

                text = await self.asr.transcribe_async(segment)
                if not text:
                    continue

                try:
                    self._translate_queue.put_nowait(("normal", text))
                except asyncio.QueueFull:
                    logger.warning("Translate queue full, dropping: %s", text[:30])

            except TimeoutError:
                continue
            except Exception:
                logger.exception("ASR worker error")
                await asyncio.sleep(0.5)

        # Flush remaining
        segments = self.vad.flush()
        for seg in segments:
            text = await self.asr.transcribe_async(seg)
            if text:
                try:
                    self._translate_queue.put_nowait(("flush", text))
                except asyncio.QueueFull:
                    pass

        try:
            self._translate_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        logger.debug("ASR worker stopped")

    async def _translate_worker(self):
        """Translate text and emit subtitles."""
        logger.debug("Translate worker started")
        while self._running.is_set():
            try:
                item = await asyncio.wait_for(self._translate_queue.get(), timeout=1.0)
                if item is None:
                    break

                task_type, text = item

                await asyncio.to_thread(self._paused.wait)

                cfg = get_config()
                use_stream = cfg.display.stream_translation

                if task_type == "flush" or not use_stream:
                    translation = await self.translator.translate_async(text)
                    self._emit_subtitle(text, translation or "...")
                else:
                    await self._stream_translate(text)

            except TimeoutError:
                continue
            except Exception:
                logger.exception("Translate worker error")
                await asyncio.sleep(0.5)

        logger.debug("Translate worker stopped")

    async def _stream_translate(self, text: str):
        """Streaming translation — emit subtitle chunks."""
        try:
            full_translation = ""
            async for chunk in self.translator.translate_stream_async(text):
                full_translation += chunk
                if self._on_subtitle_stream:
                    try:
                        self._on_subtitle_stream(text, full_translation, False)
                    except Exception:
                        logger.exception("Stream subtitle callback error")

            if self._on_subtitle_stream:
                try:
                    self._on_subtitle_stream(text, full_translation, True)
                except Exception:
                    logger.exception("Stream subtitle callback error")

            self._emit_subtitle(text, full_translation)

        except Exception:
            logger.exception("Streaming translation error")
            translation = await self.translator.translate_async(text)
            self._emit_subtitle(text, translation or "...")

    def _emit_subtitle(self, original: str, translation: str):
        """Emit subtitle event to GUI (thread-safe via Qt Signal)."""
        logger.debug("Subtitle: [orig] %s  [trans] %s", original, translation)
        if self._on_subtitle:
            try:
                self._on_subtitle(original, translation)
            except Exception:
                logger.exception("Subtitle callback error")
