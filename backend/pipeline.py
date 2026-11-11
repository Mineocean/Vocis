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

并发约定：
  - 音频线程只写缓冲 + 入队“段结束任务”，绝不改识别文本状态；
  - 增量 worker 顺序消费段任务，保证“先确认上一段，再处理下一段”；
  - 配置切换、停止都在 pipeline 自己的事件循环里完成。
"""

import asyncio
import difflib
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

import numpy as np

from .asr import create_asr
from .capture import AudioCapture
from .config import get_config, reload_config
from .diarization import Speaker, create_diarizer
from .translator import create_translator
from .vad import VoiceActivityDetector
from .work import WorkTracker

logger = logging.getLogger(__name__)

# 句子结束标点（中文/英文），用于增量翻译按句切分
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])")

# 检测语言代码 → 显示语言名（whisper info.language 输出）
_LANG_MAP = {"zh": "中文", "en": "英文", "ja": "日文"}

# 送说话人嵌入的最长音频（秒），限制内存与延迟
_MAX_DIAR_BYTES = 12 * 16000 * 2

# 停止时等待任务自行退出的时间（秒）；超时后取消并再等一段时间
_STOP_TASK_TIMEOUT = 3.0
_STOP_CANCEL_TIMEOUT = 2.0
# 停止时等待真实推理工作（线程/嵌入）结束的上限；超时后延迟释放组件
_STOP_WORK_TIMEOUT = 5.0
# 配置切换等待上限；超时后使晚到的切换失效
_APPLY_TIMEOUT = 10.0

# 发送最终帧前翻译残句的上限（秒）；超时仍发出原文
_FINAL_TRANSLATE_TIMEOUT = 15.0


@dataclass
class _SegmentJob:
    """一个 VAD 语音段的最终确认任务。

    音频线程在段边界创建它（并立即清空滚动缓冲），worker 之后按顺序处理，
    因此下一段音频不会被上一段的 finalize 误删或混入。
    """

    final_text: str | None = None   # 流式后端 end_stream() 的结果
    audio: bytes = b""              # 非流式后端：本段尚未识别的音频快照
    diar_audio: bytes = b""         # 本段用于说话人判定的音频
    speaker: Speaker | None = None  # 段内已经判定的说话人（可能为 None）
    language: str | None = None     # 本段识别语言（流式固定语言 / 段内检测）
    language_prob: float = 0.0      # 本段语言置信度


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
        self._asr_streaming = bool(self.asr.is_streaming)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._paused.set()  # Not paused initially

        self._asr_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=10)
        # (task_type, text, speaker, skip_translate)
        self._translate_queue: asyncio.Queue[
            tuple[str, str, Speaker | None, bool] | None
        ] = asyncio.Queue(maxsize=5)

        self._on_subtitle: Callable[[str, str, Speaker | None], None] | None = None
        self._on_subtitle_stream: Callable[[str, str, bool, Speaker | None], None] | None = None

        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._stop_done = False
        self._stop_had_pending = False
        # 旧组件不在任务运行中关闭；停止时统一释放
        self._retired: list[object] = []

        # 真实推理工作追踪：每个 ASR/说话人实例一个，组件关闭前必须空闲
        self._work_trackers: list[WorkTracker] = []
        self._tracked_components: list[object] = []
        self._closed_components: set[int] = set()
        self._close_lock = threading.Lock()
        self._vad_tracker = WorkTracker()
        self._track_component(self.asr)
        self._track_component(self.diarizer)
        # 配置切换令牌：超时后递增，晚到的协程不得提交
        self._apply_epoch = 0

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
        self._buffer_lock = threading.Lock()
        self._segment_jobs: deque[_SegmentJob] = deque()
        self._segment_lock = threading.Lock()
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
        """所有影响 ASR 引擎构建的字段（仅无需重建的 language 除外）。"""
        a = cfg.asr
        return (
            a.backend,
            a.api_key,
            a.base_url,
            a.model,
            a.whisper_model,
            a.whisper_model_path,
            a.whisper_device,
            a.sherpa_model_path,
        )

    @staticmethod
    def _make_diar_signature(cfg) -> tuple:
        d = cfg.diarization
        return (d.enabled, d.backend, d.max_speakers, d.threshold, d.min_seconds, d.model_path)

    # ── 真实工作追踪 / 组件释放 ───────────────────────

    def _track_component(self, component) -> WorkTracker | None:
        if component is None:
            return None
        tracker = WorkTracker()
        try:
            setattr(component, "_work_tracker", tracker)
        except Exception:
            return None
        self._work_trackers.append(tracker)
        self._tracked_components.append(component)
        return tracker

    def _close_component(self, component) -> bool:
        """Close one component only when its real work tracker is idle."""
        if component is None:
            return True
        with self._close_lock:
            if id(component) in self._closed_components:
                return True
        tracker = getattr(component, "_work_tracker", None)
        if tracker is not None and tracker.busy():
            return False
        try:
            close = getattr(component, "close", None)
            if callable(close):
                close()
        except Exception:
            logger.debug("Closing component failed", exc_info=True)
        with self._close_lock:
            self._closed_components.add(id(component))
        return True

    def _defer_close(self, components: list[object]):
        """Release components after their in-flight work finishes."""

        def run():
            # 守护线程：等真实工作结束后再释放；进程退出时不会阻塞。
            # 不用固定超时跳过 close，否则会形成长期未释放的模型。
            for component in components:
                tracker = getattr(component, "_work_tracker", None)
                if tracker is not None:
                    tracker.wait_idle()
                self._close_component(component)

        threading.Thread(target=run, name="vocis-deferred-close", daemon=True).start()

    def _release_components(self) -> list[object]:
        """Close idle components now; return those deferred due to live work."""
        components = [self.translator, self.asr, self.diarizer, *self._retired]
        deferred: list[object] = []
        seen: set[int] = set()
        for component in components:
            if component is None or id(component) in seen:
                continue
            seen.add(id(component))
            if not self._close_component(component):
                deferred.append(component)
        if deferred:
            logger.warning(
                "Deferring close of %d component(s): inference work still active",
                len(deferred),
            )
            self._defer_close(deferred)
        self._retired.clear()
        return deferred

    def _wait_for_work(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        trackers = list(self._work_trackers) + [self._vad_tracker]
        for tracker in trackers:
            remaining = max(0.0, deadline - time.monotonic())
            if not tracker.wait_idle(timeout=remaining):
                return False
        return True

    async def _call_component(self, component, fn, *args):
        """Run a sync component call in a thread, tracking the real work."""
        tracker = getattr(component, "_work_tracker", None)

        def run():
            if tracker is not None:
                tracker.begin()
            try:
                return fn(*args)
            finally:
                if tracker is not None:
                    tracker.end()

        return await asyncio.to_thread(run)

    async def _vad_process(self, chunk: np.ndarray):
        def run():
            self._vad_tracker.begin()
            try:
                return self.vad.process_chunk(chunk)
            finally:
                self._vad_tracker.end()

        return await asyncio.to_thread(run)

    def _start_event_loop(self):
        """Run asyncio event loop in a dedicated thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self) -> bool:
        """Start the pipeline."""
        if self._running.is_set():
            return True
        if not self.capture.start():
            logger.error("Failed to start audio capture")
            return False

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._start_event_loop, daemon=True)
        self._loop_thread.start()

        future = asyncio.run_coroutine_threadsafe(self._async_start(), self._loop)
        try:
            future.result(timeout=5.0)
        except Exception:
            logger.exception("Failed to start pipeline")
            self._cleanup_failed_start()
            return False

        logger.info("Pipeline started (async)")
        return True

    def _cleanup_failed_start(self):
        """启动失败：停止采集、释放组件并回收事件循环线程。"""
        self._running.clear()
        self.capture.stop()
        if self._release_components():
            self._stop_had_pending = True
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3.0)
        if loop is not None and not loop.is_closed():
            try:
                loop.close()
            except Exception:
                logger.debug("Closing event loop failed", exc_info=True)
        self._loop = None
        self._loop_thread = None
        self._tasks = []

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
        """停止 pipeline（幂等、有限等待）。"""
        if self._stop_done:
            return
        if self._stopping:
            logger.debug("Pipeline stop already in progress")
            return
        self._stopping = True
        # 作废仍在运行的 apply_config，避免停止过程中晚到切换
        self._apply_epoch += 1
        loop = self._loop
        thread = self._loop_thread
        try:
            if loop is not None and loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(self._async_stop(), loop)
                    future.result(timeout=12.0)
                except Exception:
                    logger.exception("Async stop failed or timed out")
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except Exception:
                    logger.debug("Stopping event loop failed", exc_info=True)
            if thread is not None and thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.error("Event loop thread did not exit within 5s")
        finally:
            self.capture.stop()
            # _async_stop 已处理过 release；只有它没跑到时（超时/异常）才补一次，
            # 避免对同一个忙碌组件启动两个延迟释放线程。
            if not self._stop_had_pending and self._release_components():
                self._stop_had_pending = True
            if loop is not None and not self._stop_had_pending and not loop.is_closed():
                try:
                    loop.close()
                except Exception:
                    logger.debug("Closing event loop failed", exc_info=True)
            self._loop = None
            self._loop_thread = None
            self._tasks = []
            self._stopping = False
            self._stop_done = True
            logger.info("Pipeline stopped")

    async def _async_stop(self):
        """在 pipeline 事件循环内停止 worker，并释放异步资源。

        采用“尽力 flush”：停止时 ASR worker 会把已排队/缓冲区中的语音段
        转写并交给翻译队列，但最多等待 3s；超时后取消任务，避免退出卡死。
        """
        self._running.clear()
        self._paused.set()
        with self._segment_lock:
            self._segment_jobs.clear()
        for queue in (self._asr_queue, self._translate_queue):
            self._safe_put(queue, None)

        tasks = [t for t in self._tasks if not t.done() and t is not asyncio.current_task()]
        pending: set[asyncio.Task] = set()
        if tasks:
            try:
                _, pending = await asyncio.wait(tasks, timeout=_STOP_TASK_TIMEOUT)
            except Exception:
                logger.exception("Waiting for pipeline tasks failed")
                pending = set(tasks)
            if pending:
                logger.warning(
                    "Stopping pipeline: %d task(s) still running after %.1fs, cancelling",
                    len(pending), _STOP_TASK_TIMEOUT,
                )
                for task in pending:
                    task.cancel()
                try:
                    _, still_pending = await asyncio.wait(pending, timeout=_STOP_CANCEL_TIMEOUT)
                except Exception:
                    logger.exception("Waiting for cancelled tasks failed")
                    still_pending = pending
                if still_pending:
                    logger.error(
                        "Tasks still pending after cancel (%.1fs); "
                        "leaving ASR/diarizer open to avoid releasing models mid-inference",
                        _STOP_CANCEL_TIMEOUT,
                    )
                pending = set(still_pending)

        # 已结束任务的异常也要取走，避免 "Task exception was never retrieved"
        current = asyncio.current_task()
        for task in self._tasks:
            if task is current or not task.done():
                continue
            try:
                task.exception()
            except (asyncio.CancelledError, Exception):
                pass

        # 等待真实线程/嵌入工作结束；Task 已取消不等于底层推理已退出。
        # 超时也不直接 close，而是让 _release_components 延迟释放。
        if not await asyncio.to_thread(self._wait_for_work, _STOP_WORK_TIMEOUT):
            self._stop_had_pending = True
            logger.warning("Inference work still active after stop timeout; deferring component close")
        if pending:
            self._stop_had_pending = True
            logger.warning(
                "%d background task(s) still pending; component close will be deferred",
                len(pending),
            )

        # 尽力把 ASR worker 在退出前转写出的最后几段翻译并显示完（有时间上限）
        await self._drain_pending_translations()

        try:
            await self.translator.close_async()
        except Exception:
            logger.exception("Closing translator failed")
        if self._release_components():
            self._stop_had_pending = True

    async def _drain_pending_translations(self, timeout: float = 2.0):
        """停止前把翻译队列中已识别的内容处理完，最多等待 timeout 秒。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                item = self._translate_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if item is None:
                continue
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self._handle_translate_item(item), timeout=remaining)
            except (asyncio.TimeoutError, Exception):
                logger.warning("Dropping pending translation during stop")
                return

    def _close_retired(self):
        """停止后释放切换配置时保留的旧组件（忙碌时延迟释放）。"""
        for obj in self._retired:
            if not self._close_component(obj):
                self._defer_close([obj])
        self._retired.clear()

    @staticmethod
    def _safe_put(queue: asyncio.Queue, item) -> bool:
        """非阻塞入队；满时丢弃最旧项后重试。"""
        try:
            queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(item)
                return True
            except asyncio.QueueFull:
                return False

    def pause(self):
        self._paused.clear()
        self.capture.set_enabled(False)
        logger.info("Pipeline paused")

    def resume(self):
        self._paused.set()
        self.capture.set_enabled(True)
        self.vad.reset()
        if self._running.is_set() and self._asr_streaming:
            tracker = getattr(self.asr, "_work_tracker", None)
            if tracker is not None:
                tracker.begin()
            try:
                self.asr.start_stream()
            except Exception:
                logger.exception("Failed to restart streaming ASR")
            finally:
                if tracker is not None:
                    tracker.end()
        self._reset_incremental()
        logger.info("Pipeline resumed")

    def set_language(self, lang: str):
        self._language = lang
        self.asr.set_language(lang)
        logger.info("ASR language: %s", lang)

    def apply_config(self) -> bool:
        """重新加载配置并安全重建组件；返回是否全部成功。"""
        cfg = reload_config()
        self._apply_epoch += 1
        epoch = self._apply_epoch
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._async_apply_config(cfg, live=True, epoch=epoch), loop
            )
            try:
                return bool(future.result(timeout=_APPLY_TIMEOUT))
            except FutureTimeout:
                # 让仍在运行的协程在下一个检查点放弃提交，避免晚到切换
                self._apply_epoch += 1
                future.cancel()
                logger.error("apply_config timed out after %.1fs; late swap aborted", _APPLY_TIMEOUT)
                return False
            except Exception:
                logger.exception("apply_config failed")
                return False
        try:
            return bool(asyncio.run(self._async_apply_config(cfg, live=False, epoch=epoch)))
        except Exception:
            logger.exception("apply_config failed")
            return False

    def _apply_is_stale(self, epoch: int | None) -> bool:
        return epoch is not None and epoch != self._apply_epoch

    async def _async_apply_config(self, cfg, live: bool, epoch: int | None = None) -> bool:
        if self._apply_is_stale(epoch):
            return False
        self._language = cfg.asr.language
        self.incremental_enabled = cfg.incremental_enabled
        self._incremental_interval = cfg.incremental_interval
        self._incremental_max_seconds = cfg.incremental_max_seconds
        self._stream_sentence_chars = cfg.stream_sentence_chars
        ok = True

        # 翻译客户端：先创建，等 ASR 就绪/未超时后再提交，避免超时后仍然切换
        old_translator = self.translator
        new_translator = None
        try:
            new_translator = create_translator()
        except Exception:
            logger.exception("Failed to rebuild translator, keeping previous one")
            ok = False

        # ASR：所有影响引擎构建的字段变了才重建
        signature = self._make_asr_signature(cfg)
        if signature != self._asr_signature:
            new_asr = None
            try:
                new_asr = create_asr()
                actual_backend = getattr(new_asr, "backend", "") or cfg.asr.backend
                if actual_backend != cfg.asr.backend.lower():
                    logger.error(
                        "ASR rebuild fell back to '%s' instead of '%s'; keeping previous engine",
                        actual_backend, cfg.asr.backend,
                    )
                    self._close_component(new_asr)
                    new_asr = None
                    ok = False
                else:
                    self._track_component(new_asr)
                    # 新实例必须先达到可用状态，才允许替换旧实例。
                    if live and new_asr.is_streaming:
                        await self._call_component(new_asr, new_asr.start_stream)
                    else:
                        prepare = getattr(new_asr, "prepare", None)
                        if callable(prepare):
                            await self._call_component(new_asr, prepare)
                    is_ready = getattr(new_asr, "is_ready", None)
                    if callable(is_ready) and not is_ready():
                        raise RuntimeError(
                            f"ASR backend '{cfg.asr.backend}' did not reach ready state"
                        )
                    if self._apply_is_stale(epoch):
                        logger.warning("apply_config became stale; aborting late ASR swap")
                        self._close_component(new_asr)
                        if new_translator is not None:
                            self._close_component(new_translator)
                        new_asr = None
                        return False
                    old_asr = self.asr
                    self.asr = new_asr
                    new_asr = None  # 所有权已转移，异常路径不得再关闭
                    self._asr_streaming = bool(self.asr.is_streaming)
                    self._asr_signature = signature
                    self._retire(old_asr, live)
                    logger.info("ASR backend rebuilt: %s", cfg.asr.backend)
            except asyncio.CancelledError:
                # apply_config 超时会取消协程；prepare/start_stream 可能仍在线程里。
                # 不能让新实例泄漏，也不能提前 close 正在加载的模型。
                if new_asr is not None and not self._close_component(new_asr):
                    self._defer_close([new_asr])
                if new_translator is not None:
                    self._close_component(new_translator)
                raise
            except Exception:
                logger.exception("Failed to rebuild ASR backend, keeping previous one")
                if new_asr is not None and not self._close_component(new_asr):
                    self._defer_close([new_asr])
                ok = False
        else:
            self.asr.set_language(cfg.asr.language)

        # 说话人：开关/后端/参数变了才重建（模型加载/下载较慢）
        diar_signature = self._make_diar_signature(cfg)
        if diar_signature != self._diar_signature:
            try:
                new_diarizer = create_diarizer()
                self._track_component(new_diarizer)
                if self._apply_is_stale(epoch):
                    self._close_component(new_diarizer)
                    ok = False
                else:
                    old_diarizer = self.diarizer
                    self.diarizer = new_diarizer
                    self._diar_signature = diar_signature
                    self._retire(old_diarizer, live)
            except Exception:
                logger.exception("Failed to rebuild diarizer, keeping previous one")
                ok = False

        if self._apply_is_stale(epoch):
            if new_translator is not None:
                self._close_component(new_translator)
            return False
        if new_translator is not None:
            self.translator = new_translator
            self._retire(old_translator, live)
            logger.info(
                "Translator: %s (%s @ %s)",
                cfg.translator.provider, cfg.translator.model, cfg.translator.base_url,
            )

        self._reset_incremental()
        logger.info(
            "Config applied: ASR=%s, provider=%s, target=%s, diarization=%s, ok=%s",
            cfg.asr.backend, cfg.translator.provider, cfg.translator.target_language,
            cfg.diarization.enabled, ok,
        )
        return ok

    def _retire(self, component, live: bool):
        """保留旧组件直到停止，避免在旧识别任务仍在执行时释放模型。"""
        if component is None:
            return
        if live:
            self._retired.append(component)
        else:
            if not self._close_component(component):
                self._defer_close([component])

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
                speech_segments = await self._vad_process(chunk)

                if self.incremental_enabled:
                    pcm = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    self._extend_diar_audio(pcm)
                    if self._asr_streaming:
                        await self._call_component(self.asr, self.asr.push_audio, pcm)
                        if speech_segments:
                            # 段边界立即封口：end_stream + 新流，避免下一段音频混入
                            await self._finish_stream_segment()
                    else:
                        self._extend_rolling_audio(pcm)
                        if speech_segments:
                            self._enqueue_segment_job(
                                audio=self._take_rolling_audio(),
                                language=self._current_lang,
                                language_prob=self._current_lang_prob,
                            )
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

    # ── 段缓冲 / 段任务 ───────────────────────────────

    def _max_rolling_bytes(self) -> int:
        return max(1, int(self._incremental_max_seconds * 16000 * 2))

    def _extend_rolling_audio(self, pcm: bytes):
        with self._buffer_lock:
            self._rolling_audio.extend(pcm)
            limit = self._max_rolling_bytes()
            if len(self._rolling_audio) > limit:
                del self._rolling_audio[: len(self._rolling_audio) - limit]

    def _take_rolling_audio(self) -> bytes:
        with self._buffer_lock:
            audio = bytes(self._rolling_audio)
            self._rolling_audio.clear()
            return audio

    def _snapshot_rolling_audio(self) -> bytes:
        with self._buffer_lock:
            return bytes(self._rolling_audio)

    def _extend_diar_audio(self, pcm: bytes):
        with self._buffer_lock:
            self._diar_audio.extend(pcm)
            if len(self._diar_audio) > _MAX_DIAR_BYTES:
                del self._diar_audio[: len(self._diar_audio) - _MAX_DIAR_BYTES]

    def _enqueue_segment_job(
        self,
        *,
        final_text: str | None = None,
        audio: bytes = b"",
        language: str | None = None,
        language_prob: float = 0.0,
    ):
        with self._buffer_lock:
            diar_audio = bytes(self._diar_audio)
            self._diar_audio.clear()
            speaker = self._segment_speaker
            self._segment_speaker = None
        with self._segment_lock:
            self._segment_jobs.append(
                _SegmentJob(
                    final_text=final_text,
                    audio=audio,
                    diar_audio=diar_audio,
                    speaker=speaker,
                    language=language,
                    language_prob=language_prob,
                )
            )

    async def _finish_stream_segment(self):
        """流式后端在段边界封口：取最终文本并开启新流。"""
        final = ""
        try:
            final = await self._call_component(self.asr, self.asr.end_stream)
        except Exception:
            logger.exception("Failed to finalize streaming ASR segment")
        fixed_lang = getattr(self.asr, "fixed_language", None)
        language = fixed_lang or self._current_lang
        prob = 1.0 if fixed_lang else self._current_lang_prob
        final_text = final.strip() if isinstance(final, str) else ""
        self._enqueue_segment_job(
            final_text=final_text or None,
            language=language,
            language_prob=prob,
        )
        # 先发段结束信号，worker 就不会把新流的 partial 算进旧段
        self._segment_end.set()
        try:
            await self._call_component(self.asr, self.asr.start_stream)
        except Exception:
            logger.exception("Failed to restart streaming ASR")

    async def _drain_segment_jobs(self):
        """按顺序确认所有已结束的段；每段只发一次最终帧。"""
        while True:
            with self._segment_lock:
                job = self._segment_jobs.popleft() if self._segment_jobs else None
            if job is None:
                break
            try:
                await self._finalize_segment(job)
            except Exception:
                logger.exception("Finalizing speech segment failed")
            finally:
                self._reset_segment_state()
        self._segment_end.clear()

    async def _finalize_segment(self, job: _SegmentJob):
        speaker = job.speaker
        if (
            speaker is None
            and self.diarizer is not None
            and len(job.diar_audio) >= int(0.5 * 16000) * 2
        ):
            try:
                speaker = await self.diarizer.assign_async(job.diar_audio)
            except Exception:
                logger.exception("Speaker diarization error")

        final_text = job.final_text
        language = job.language
        language_prob = job.language_prob
        if not self._asr_streaming and job.audio:
            # 这里的音频已经过 VAD（>= min_speech_duration），门槛放宽，
            # 否则 0.3s 的短句会在第一次周期识别前被丢掉。
            if self._audio_has_speech(job.audio, min_seconds=0.2):
                try:
                    result = await self.asr.transcribe_async(job.audio)
                except Exception:
                    logger.exception("Final ASR failed, keeping partial text")
                    result = None
                if result:
                    try:
                        text, final_lang, final_prob = result
                        text = text.strip() if isinstance(text, str) else ""
                    except (TypeError, ValueError):
                        logger.error("Unexpected ASR result: %r", result)
                        text = ""
                    if text:
                        final_text = text
                        # 最终识别自带的语言才是本段决策依据；None/低置信度走翻译
                        language = final_lang if isinstance(final_lang, str) and final_lang else None
                        try:
                            language_prob = float(final_prob or 0.0)
                        except (TypeError, ValueError):
                            language_prob = 0.0
            else:
                logger.debug("Segment has no speech, skipping final ASR")

        # 合并 final 与 partial：最终文本以 final 为准，只保留尚未确认的部分
        if final_text:
            final = final_text.strip()
            if final:
                self._residual = self._merge_final_text(final).strip()
                self._last_text = final

        has_content = bool(
            self._last_text.strip() or self._confirmed_sentences or self._confirmed_trans.strip()
        )
        if not has_content:
            logger.debug("Segment finished without text, no subtitle emitted")
            return

        # 本段自己的语言/置信度决定跳译，不复用上一段留下的全局状态
        self._skip_translate = self._should_skip_translate(language, language_prob)

        try:
            await asyncio.wait_for(
                self._flush_residual(speaker), timeout=_FINAL_TRANSLATE_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("Final translation timed out; emitting original text")
            self._emit_stream(self._last_text.strip(), self._confirmed_trans, True, speaker)
            self._residual = ""
        except Exception:
            logger.exception("Flushing final segment failed; emitting original text")
            self._emit_stream(self._last_text.strip(), self._confirmed_trans, True, speaker)
            self._residual = ""

    # ── 说话人 ────────────────────────────────────────

    async def _ensure_segment_speaker(self) -> Speaker | None:
        """每个 VAD 段只判一次说话人，段内所有字幕沿用同一标签。"""
        if self.diarizer is None:
            return None
        if self._segment_speaker is not None:
            return self._segment_speaker
        with self._buffer_lock:
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

    def _reset_segment_state(self):
        """只清空“本段文本/说话人”状态，不动段任务队列。"""
        self._last_text = ""
        self._confirmed_sentences.clear()
        self._confirmed_trans = ""
        self._residual = ""
        self._current_lang = None
        self._current_lang_prob = 0.0
        self._skip_translate = False

    def _reset_incremental(self):
        """完全重置增量识别状态（暂停/恢复、切换配置、停止时）。"""
        with self._buffer_lock:
            self._rolling_audio.clear()
            self._diar_audio.clear()
        with self._segment_lock:
            self._segment_jobs.clear()
        self._segment_speaker = None
        self._segment_end.clear()
        self._reset_segment_state()

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
        if not isinstance(lang, str) or not lang or lang not in _LANG_MAP:
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

            # 段结束：先确认最终文本/残句，再进入下一段
            # （段边界可能在 sleep/唤醒期间或上一次 ASR await 期间产生）
            if self._segment_end.is_set():
                await self._drain_segment_jobs()
                continue

            if self._asr_streaming:
                try:
                    text = await self._call_component(self.asr, self.asr.get_partial_text)
                except Exception:
                    logger.exception("Streaming ASR error")
                    continue
                # 读取期间段可能已经封口并开启新流，旧 partial 不能算进新段
                if self._segment_end.is_set():
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

            audio = self._snapshot_rolling_audio()
            if not audio:
                continue

            # 门禁：过短或纯静音的碎片不送 ASR，避免 whisper 幻觉文本
            if not self._audio_has_speech(audio):
                continue

            # 截断过长的滚动缓冲，避免云端 ASR 处理超时
            max_bytes = self._max_rolling_bytes()
            if len(audio) > max_bytes:
                audio = audio[-max_bytes:]

            try:
                result = await self.asr.transcribe_async(audio)
            except Exception:
                logger.exception("Incremental ASR error")
                continue
            if not result:
                continue
            try:
                text, lang, prob = result
            except (TypeError, ValueError):
                logger.error("Unexpected ASR result: %r", result)
                continue
            text = (text or "").strip()
            if not text:
                continue

            # 记录检测语言并决定本段是否跳过翻译（源语言 == 目标语言）
            self._current_lang = lang
            self._current_lang_prob = float(prob or 0.0)
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

    def _merge_final_text(self, final: str) -> str:
        """计算 final 中尚未确认（未翻译）的尾部文本。

        - 没有任何已确认句子时，整段都还没翻译，直接使用 final（避免重复追加）；
        - 有已确认句子时，从 confirmed 之后截取，final 修正已确认词的修正不会重复；
        - confirmed 与 final 对不上（例如 final 只覆盖末尾窗口）时退回文本差分。
        """
        confirmed = "".join(self._confirmed_sentences).strip()
        if not confirmed:
            return final
        if final.startswith(confirmed):
            return final[len(confirmed):]
        sm = difflib.SequenceMatcher(None, confirmed, final, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size >= 3]
        if blocks:
            last = blocks[-1]
            return final[last.b + last.size:]
        return self._diff_text(self._last_text, final)

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
        """段结束最终确认：翻译残句并发出最终帧。

        即使没有残句（句子刚好完整结束），只要本段有内容也必须发最终帧，
        否则界面不会启动自动隐藏计时。
        """
        residual = self._residual.strip()
        if residual and not self._skip_translate:
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
        self._residual = ""
        original = self._last_text.strip() or "".join(self._confirmed_sentences).strip()
        if original or self._confirmed_trans.strip():
            self._emit_stream(original, self._confirmed_trans, True, speaker)

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

    # ── 普通段落模式 ──────────────────────────────────

    async def _transcribe_segment(
        self, segment: bytes
    ) -> tuple[str, str | None, float] | None:
        """识别一段音频并统一解包为 (text, lang, probability)。"""
        try:
            result = await self.asr.transcribe_async(segment)
        except Exception:
            logger.exception("ASR transcription failed")
            return None
        if not result:
            return None
        try:
            text, lang, prob = result
        except (TypeError, ValueError):
            logger.error("Unexpected ASR result: %r", result)
            return None
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            return None
        if not isinstance(lang, str) or not lang:
            lang = None
        return text, lang, float(prob or 0.0)

    def _queue_translation(
        self,
        text: str,
        lang: str | None,
        prob: float,
        speaker: Speaker | None,
        task_type: str,
    ):
        """入队前就把“是否跳译”算好，队列里只放纯文本。"""
        item = (task_type, text, speaker, self._should_skip_translate(lang, prob))
        if not self._safe_put(self._translate_queue, item):
            logger.warning("Translate queue full, dropping: %s", text[:30])

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

                result = await self._transcribe_segment(segment)
                if result is None:
                    continue
                text, lang, prob = result
                self._queue_translation(text, lang, prob, speaker, "normal")

            except TimeoutError:
                continue
            except Exception:
                logger.exception("ASR worker error")
                await asyncio.sleep(0.5)

        # Flush remaining（尽力而为；取消/超时由 stop() 控制）
        remaining: list[bytes] = []
        while True:
            try:
                item = self._asr_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item:
                remaining.append(item)
        remaining.extend(self.vad.flush())
        for seg in remaining:
            result = await self._transcribe_segment(seg)
            if result is None:
                continue
            text, lang, prob = result
            self._queue_translation(text, lang, prob, None, "flush")

        self._safe_put(self._translate_queue, None)
        logger.debug("ASR worker stopped")

    async def _translate_worker(self):
        """Translate text and emit subtitles."""
        logger.debug("Translate worker started")
        while self._running.is_set():
            try:
                item = await asyncio.wait_for(self._translate_queue.get(), timeout=1.0)
                if item is None:
                    break
                await self._handle_translate_item(item)
            except TimeoutError:
                continue
            except Exception:
                logger.exception("Translate worker error")
                await asyncio.sleep(0.5)

        logger.debug("Translate worker stopped")

    async def _handle_translate_item(
        self, item: tuple[str, str, Speaker | None, bool]
    ):
        task_type, text, speaker, skip_translate = item
        await asyncio.to_thread(self._paused.wait)
        if skip_translate:
            # 源语言 == 目标语言：保留原文字幕，不显示失败占位符
            self._emit_subtitle(text, "", speaker)
            return
        cfg = get_config()
        if task_type == "flush" or not cfg.display.stream_translation:
            translation = await self.translator.translate_async(text)
            self._emit_subtitle(text, translation or "", speaker)
        else:
            await self._stream_translate(text, speaker)

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
            self._emit_subtitle(text, translation or "", speaker)

    def _emit_subtitle(self, original: str, translation: str, speaker: Speaker | None = None):
        """Emit subtitle event to GUI (thread-safe via Qt Signal)."""
        logger.info("Subtitle: [orig] %s  [trans] %s", original[:120], translation[:120])
        if self._on_subtitle:
            try:
                self._on_subtitle(original, translation, speaker)
            except Exception:
                logger.exception("Subtitle callback error")
