"""
Main pipeline — Audio capture → VAD → ASR → (speaker) → Translation → GUI.

Async architecture:
  - Audio feeder coroutine reads audio and runs VAD in a worker thread
  - ASR worker coroutine transcribes speech to text
  - Translate worker coroutine translates text and emits subtitles
  - Incremental worker (default) re-recognizes a rolling window and emits
    sentence-level subtitles as they are recognized

说话人分离：每个 VAD 语音段做一次说话人嵌入 + 在线聚类，
字幕回调带上 Speaker（短段沿用上一位，未确认时为 None）。
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
from .diarization import Speaker, create_diarizer
from .translator import create_translator
from .vad import VoiceActivityDetector

logger = logging.getLogger(__name__)

# 句子结束标点（中文/英文），用于增量翻译按句切分
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])")

# 检测语言代码 → 显示语言名（whisper info.language 输出）
_LANG_MAP = {"zh": "中文", "en": "英文", "ja": "日文"}

# 送说话人嵌入的最长音频（秒），限制内存与延迟
_MAX_DIAR_BYTES = 12 * 16000 * 2


class SubtitlePipeline:
    """
    Async subtitle pipeline.

    Coroutines: audio_feeder → asr_worker → translate_worker
                (or audio_feeder → incremental_worker) when 增量模式 开启
    """

    def __init__(self):
        self.capture = AudioCapture()
        self.vad = VoiceActivityDetector()
        self.asr = create_asr()
        self.translator = create_translator()
        self.diarizer = create_diarizer()
        self._asr_streaming = bool(getattr(self.asr, "is_streaming", False))

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._paused.set()  # Not paused initially

        self._asr_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=10)
        self._translate_queue: asyncio.Queue[tuple[str, str, Speaker | None] | None] = asyncio.Queue(
            maxsize=5
        )

        self._on_subtitle: Callable[[str, str, Speaker | None], None] | None = None
        self._on_subtitle_stream: Callable[[str, str, bool, Speaker | None], None] | None = None

        self._tasks: list[asyncio.Task] = []

        cfg = get_config()
        self._language = cfg.asr.language
        self._asr_signature = self._make_asr_signature(cfg)
        self._diar_signature = self._make_diar_signature(cfg)

        # ── 增量实时识别（方案 D）状态 ──
        self.incremental_enabled = cfg.incremental_enabled
        self._incremental_interval = cfg.incremental_interval
        self._incremental_max_seconds = cfg.incremental_max_seconds
        self._stream_sentence_chars = cfg.stream_sentence_chars
        self._rolling_audio: bytearray = bytearray()   # 累积的 int16 PCM（本段）
        self._diar_audio: bytearray = bytearray()      # 说话人嵌入用的本段音频
        self._segment_speaker: Speaker | None = None
        self._last_text = ""                            # 上一次 ASR 全文
        self._confirmed_sentences: list[str] = []       # 已翻译的完整句子原文
        self._confirmed_trans = ""                      # 已确认译文（追加式）
        self._residual = ""                             # 当前未完整句子（段结束才翻译）
        self._segment_end = threading.Event()           # VAD 段结束信号
        self._current_lang: str | None = None           # 当前检测到的源语言代码
        self._current_lang_prob = 0.0                   # 语言置信度
        self._skip_translate = False                    # 本段是否跳过翻译（源==目标）

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()

    @property
    def current_language(self) -> str:
        return self._language

    def on_subtitle(self, callback: Callable[[str, str, Speaker | None], None]):
        self._on_subtitle = callback

    def on_subtitle_stream(self, callback: Callable[[str, str, bool, Speaker | None], None]):
        self._on_subtitle_stream = callback

    @staticmethod
    def _make_asr_signature(cfg) -> tuple:
        return (cfg.asr.backend, cfg.asr.base_url, cfg.asr.model, cfg.asr.language)

    @staticmethod
    def _make_diar_signature(cfg) -> tuple:
        d = cfg.diarization
        return (d.enabled, d.backend, d.max_speakers, d.threshold, d.min_seconds, d.model_path)

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

        self._tasks = [asyncio.create_task(self._audio_feeder(), name="audio_feeder")]
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

        try:
            asyncio.run_coroutine_threadsafe(self._asr_queue.put(None), self._loop).result(timeout=2.0)
            asyncio.run_coroutine_threadsafe(self._translate_queue.put(None), self._loop).result(
                timeout=2.0
            )

            for task in self._tasks:
                self._loop.call_soon_threadsafe(task.cancel)

            try:
                future = asyncio.run_coroutine_threadsafe(
                    asyncio.gather(*self._tasks, return_exceptions=True), self._loop
                )
                future.result(timeout=5.0)
            except Exception:
                pass

            try:
                asyncio.run_coroutine_threadsafe(self.translator.close_async(), self._loop).result(
                    timeout=2.0
                )
            except Exception:
                pass
        except Exception:
            pass

        self.capture.stop()
        self.asr.close()
        if self.diarizer is not None:
            self.diarizer.close()

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
        if self._asr_streaming:
            try:
                self.asr.start_stream()
            except Exception:
                logger.exception("Failed to restart streaming ASR")
        self._reset_incremental()
        logger.info("Pipeline resumed")

    def set_language(self, lang: str):
        self._language = lang
        self.asr.set_language(lang)
        logger.info("ASR language: %s", lang)

    def apply_config(self):
        """重新加载配置；提供商/说话人设置变了就重建对应组件。"""
        cfg = reload_config()

        self._language = cfg.asr.language
        self.incremental_enabled = cfg.incremental_enabled
        self._incremental_interval = cfg.incremental_interval
        self._incremental_max_seconds = cfg.incremental_max_seconds
        self._stream_sentence_chars = cfg.stream_sentence_chars

        # 翻译客户端：总是重建（廉价、懒连接），保证换提供商/目标语言后缓存不串味
        old_translator = self.translator
        try:
            self.translator = create_translator()
            logger.info(
                "Translator: %s (%s @ %s)",
                cfg.translator.provider, cfg.translator.model, cfg.translator.base_url,
            )
        except Exception:
            logger.exception("Failed to rebuild translator, keeping previous one")
        if old_translator is not None and old_translator is not self.translator:
            try:
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(old_translator.close_async(), self._loop)
                else:
                    old_translator.close()
            except Exception:
                logger.debug("Closing previous translator failed", exc_info=True)

        # ASR：只在后端/端点/语言真的变了时重建
        signature = self._make_asr_signature(cfg)
        if signature != self._asr_signature:
            try:
                new_asr = create_asr()
                old_asr = self.asr
                self.asr = new_asr
                self._asr_streaming = bool(getattr(new_asr, "is_streaming", False))
                self._asr_signature = signature
                old_asr.close()
                logger.info("ASR backend rebuilt: %s", cfg.asr.backend)
            except Exception:
                logger.exception("Failed to rebuild ASR backend, keeping previous one")
        else:
            self.asr.set_language(cfg.asr.language)

        # 说话人：开关/后端/参数变了才重建（模型加载/下载较慢）
        diar_signature = self._make_diar_signature(cfg)
        if diar_signature != self._diar_signature:
            if self.diarizer is not None:
                self.diarizer.close()
            self.diarizer = create_diarizer()
            self._diar_signature = diar_signature

        self._reset_incremental()
        logger.info(
            "Config applied: ASR=%s, provider=%s, target=%s, diarization=%s",
            cfg.asr.backend, cfg.translator.provider, cfg.translator.target_language,
            cfg.diarization.enabled,
        )

    def reset_context(self):
        self.translator.reset_context()
        self.vad.reset()
        if self.diarizer is not None:
            self.diarizer.reset()
        self._reset_incremental()

    # ── Async coroutines ──────────────────────────────

    async def _audio_feeder(self):
        """Read audio from capture device and feed to VAD (VAD runs off-loop)."""
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

                # VAD 是 ONNX 推理，放到线程池，避免阻塞事件循环
                speech_segments = await asyncio.to_thread(self.vad.process_chunk, chunk)

                if self.incremental_enabled:
                    pcm = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    # 说话人嵌入用的音频（两种 ASR 模式都要）
                    self._diar_audio.extend(pcm)
                    if len(self._diar_audio) > _MAX_DIAR_BYTES:
                        del self._diar_audio[: len(self._diar_audio) - _MAX_DIAR_BYTES]
                    if self._asr_streaming:
                        await asyncio.to_thread(self.asr.push_audio, pcm)
                        if speech_segments:
                            self._segment_end.set()
                    else:
                        self._rolling_audio.extend(pcm)
                        if speech_segments:
                            self._segment_end.set()
                else:
                    for segment in speech_segments:
                        try:
                            self._asr_queue.put_nowait(segment)
                        except asyncio.QueueFull:
                            logger.warning("ASR queue full, dropping segment")
            except Exception:
                logger.exception("Audio feeder error")
                await asyncio.sleep(0.5)
        logger.debug("Audio feeder stopped")

    # ── 说话人 ────────────────────────────────────────

    async def _ensure_segment_speaker(self) -> Speaker | None:
        """每个 VAD 段只判一次说话人，段内所有字幕沿用同一标签。"""
        if self.diarizer is None:
            return None
        if self._segment_speaker is not None:
            return self._segment_speaker
        audio = bytes(self._diar_audio)
        if len(audio) < int(0.5 * 16000) * 2:
            return None
        try:
            self._segment_speaker = await self.diarizer.assign_async(audio)
        except Exception:
            logger.exception("Speaker diarization error")
        return self._segment_speaker

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
        last = parts[-1] if parts else ""
        if parts and (not last or not _SENTENCE_RE.search(last)):
            complete = parts[:-1]
        else:
            complete = parts
            last = ""
        return [p for p in complete if p and p.strip()], (last or "")

    def _reset_incremental(self):
        self._rolling_audio.clear()
        self._diar_audio.clear()
        self._segment_speaker = None
        self._last_text = ""
        self._confirmed_sentences.clear()
        self._confirmed_trans = ""
        self._residual = ""
        self._segment_end.clear()
        self._current_lang = None
        self._current_lang_prob = 0.0
        self._skip_translate = False

    @staticmethod
    def _audio_has_speech(audio: bytes, min_seconds: float = 0.4,
                          rms_threshold: float = 0.005) -> bool:
        """判断滚动音频是否值得送 ASR：时长足够且非静音。

        避免把 0.2s 碎片或纯静音喂给 whisper，whisper 对这类输入
        会产生幻觉文本并导致语言检测抖动。
        """
        n = len(audio) // 2
        if n < int(min_seconds * 16000):
            return False
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(samples)))) if n else 0.0
        return rms >= rms_threshold

    @staticmethod
    def _map_lang(lang: str | None) -> str:
        """检测语言代码 → 显示语言名（未知语言返回 '中文' 保守处理）。"""
        if not lang:
            return "中文"
        return _LANG_MAP.get(lang, "中文")

    def _should_skip_translate(self, lang: str | None, prob: float) -> bool:
        """源语言 == 目标语言时跳过翻译；低置信度保守走翻译。"""
        cfg = get_config()
        if not cfg.asr.skip_translate_when_same_lang:
            return False
        if prob < 0.5:
            return False
        mapped = self._map_lang(lang)
        return mapped == cfg.translator.target_language

    async def _incremental_worker(self):
        """周期性识别滚动音频，差分出新增完整句子并增量翻译。"""
        logger.debug("Incremental worker started")
        while self._running.is_set():
            await asyncio.sleep(self._incremental_interval)
            await asyncio.to_thread(self._paused.wait)
            if not self._running.is_set():
                break

            # 段结束：先定说话人，再翻译残句作为最终确认，然后重置本段状态
            if self._segment_end.is_set():
                speaker = await self._ensure_segment_speaker()
                await self._flush_residual(speaker)
                if self._asr_streaming:
                    final = await asyncio.to_thread(self.asr.end_stream)
                    if final and final.strip():
                        logger.debug("Sherpa final segment: %s", final.strip())
                    await asyncio.to_thread(self.asr.start_stream)
                self._reset_incremental()
                continue

            if self._asr_streaming:
                try:
                    text = await asyncio.to_thread(self.asr.get_partial_text)
                except Exception:
                    logger.exception("Streaming ASR error")
                    continue
                text = (text or "").strip()
                if not text:
                    continue

                # sherpa 固定中文模型，语言恒定
                self._current_lang = "zh"
                self._current_lang_prob = 1.0
                self._skip_translate = self._should_skip_translate("zh", 1.0)

                new_text = self._diff_text(self._last_text, text)
                self._last_text = text
                if not new_text:
                    continue

                # sherpa 输出无标点，无法按句子结束标点切分，改为按字数强制切句
                self._residual += new_text
                emitted = False
                while len(self._residual) >= self._stream_sentence_chars:
                    sent = self._residual[:self._stream_sentence_chars]
                    self._residual = self._residual[self._stream_sentence_chars:]
                    await self._translate_sentences([sent])
                    self._confirmed_sentences.append(sent)
                    emitted = True
                if emitted:
                    speaker = await self._ensure_segment_speaker()
                    self._emit_stream(text, self._confirmed_trans, False, speaker)
                continue

            audio = bytes(self._rolling_audio)
            if not audio:
                continue

            # 门禁：过短或纯静音的碎片不送 ASR，避免 whisper 幻觉文本
            if not self._audio_has_speech(audio):
                continue

            # 截断过长的滚动缓冲，避免云端 ASR 处理超时
            max_bytes = int(self._incremental_max_seconds * 16000 * 2)
            if len(audio) > max_bytes:
                audio = audio[-max_bytes:]

            try:
                result = await self.asr.transcribe_async(audio)
            except Exception:
                logger.exception("Incremental ASR error")
                continue
            if not result:
                continue
            text, lang, prob = result
            text = text.strip()
            if not text:
                continue

            # 记录检测语言并决定本段是否跳过翻译（源语言 == 目标语言）
            self._current_lang = lang
            self._current_lang_prob = prob
            self._skip_translate = self._should_skip_translate(lang, prob)

            new_text = self._diff_text(self._last_text, text)
            self._last_text = text

            pool = (self._residual + new_text) if self._residual else new_text
            sentences, residual = self._split_sentences(pool)
            new_sentences = self._diff_sentences(self._confirmed_sentences, sentences)
            if new_sentences:
                await self._translate_sentences(new_sentences)
                self._confirmed_sentences = sentences
                speaker = await self._ensure_segment_speaker()
                self._emit_stream(text, self._confirmed_trans, False, speaker)

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
            # 跳译模式（源语言 == 目标语言）：译文保持为空，字幕只显示原文
            if self._skip_translate:
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

    async def _flush_residual(self, speaker: Speaker | None = None):
        """段结束时翻译尚未处理的残句（最终确认）。"""
        residual = self._residual.strip()
        if not residual:
            return
        if not self._skip_translate:
            try:
                translation = await self.translator.translate_async(residual)
            except Exception:
                logger.exception("Incremental flush translate error")
                translation = None
            if translation:
                self._confirmed_trans = (
                    (self._confirmed_trans + " " + translation).strip()
                    if self._confirmed_trans
                    else translation
                )
        # 无论翻译成功与否都发出最终帧：原文不能丢
        if self._last_text.strip():
            self._emit_stream(self._last_text, self._confirmed_trans, True, speaker)
        self._residual = ""

    def _emit_stream(
        self, original: str, translation: str, is_final: bool, speaker: Speaker | None = None
    ):
        if is_final:
            logger.info(
                "Subtitle final: [orig] %s [trans] %s [speaker] %s",
                original[:120],
                translation[:120],
                speaker.id if speaker else "-",
            )
        if self._on_subtitle_stream:
            try:
                self._on_subtitle_stream(original, translation, is_final, speaker)
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

                # 段落模式：整段先判说话人，再识别
                speaker: Speaker | None = None
                if self.diarizer is not None:
                    try:
                        speaker = await self.diarizer.assign_async(segment)
                    except Exception:
                        logger.exception("Speaker diarization error")

                text = await self.asr.transcribe_async(segment)
                if not text:
                    continue

                try:
                    self._translate_queue.put_nowait(("normal", text, speaker))
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
                    self._translate_queue.put_nowait(("flush", text, None))
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

                task_type, text, speaker = item

                await asyncio.to_thread(self._paused.wait)

                cfg = get_config()
                use_stream = cfg.display.stream_translation

                if task_type == "flush" or not use_stream:
                    translation = await self.translator.translate_async(text)
                    self._emit_subtitle(text, translation or "...", speaker)
                else:
                    await self._stream_translate(text, speaker)

            except TimeoutError:
                continue
            except Exception:
                logger.exception("Translate worker error")
                await asyncio.sleep(0.5)

        logger.debug("Translate worker stopped")

    async def _stream_translate(self, text: str, speaker: Speaker | None = None):
        """Streaming translation — emit subtitle chunks."""
        try:
            full_translation = ""
            async for chunk in self.translator.translate_stream_async(text):
                full_translation += chunk
                self._emit_stream(text, full_translation, False, speaker)
            self._emit_stream(text, full_translation, True, speaker)
            self._emit_subtitle(text, full_translation, speaker)
        except Exception:
            logger.exception("Streaming translation error")
            translation = await self.translator.translate_async(text)
            self._emit_subtitle(text, translation or "...", speaker)

    def _emit_subtitle(self, original: str, translation: str, speaker: Speaker | None = None):
        """Emit subtitle event to GUI (thread-safe via Qt Signal)."""
        logger.info("Subtitle: [orig] %s  [trans] %s", original[:120], translation[:120])
        if self._on_subtitle:
            try:
                self._on_subtitle(original, translation, speaker)
            except Exception:
                logger.exception("Subtitle callback error")
