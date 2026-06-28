"""
Main pipeline — Audio capture → VAD → ASR → Translation → GUI.

Async architecture:
  - Audio feeder coroutine reads audio from capture device
  - VAD processor coroutine splits audio into speech segments
  - ASR worker coroutine transcribes speech to text
  - Translate worker coroutine translates text and emits subtitles
"""

import asyncio
import logging
import threading
from typing import Callable, Optional

from .capture import AudioCapture
from .vad import VoiceActivityDetector
from .asr import create_asr
from .translator import DeepSeekTranslator
from .config import get_config, reload_config

logger = logging.getLogger(__name__)


class SubtitlePipeline:
    """
    Async subtitle pipeline.

    Coroutines: audio_feeder → vad_processor → asr_worker → translate_worker
    """

    def __init__(self):
        self.capture = AudioCapture()
        self.vad = VoiceActivityDetector()
        self.asr = create_asr()
        self.translator = DeepSeekTranslator()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._running = asyncio.Event()
        self._paused = asyncio.Event()
        self._paused.set()  # Not paused initially

        self._asr_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=10)
        self._translate_queue: asyncio.Queue[Optional[tuple[str, str]]] = asyncio.Queue(maxsize=5)

        self._on_subtitle: Optional[Callable[[str, str], None]] = None
        self._on_subtitle_stream: Optional[Callable[[str, str, bool], None]] = None

        # Futures for cross-thread communication
        self._tasks: list[asyncio.Task] = []

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()

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
            asyncio.create_task(self._vad_processor(), name="vad_processor"),
            asyncio.create_task(self._asr_worker(), name="asr_worker"),
            asyncio.create_task(self._translate_worker(), name="translate_worker"),
        ]
        logger.info("Async tasks started")

    def stop(self):
        """Stop the pipeline."""
        if self._loop is None:
            return

        self._running.clear()
        self._paused.set()  # Unblock any paused coroutines

        # Signal workers to stop
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

        self.capture.stop()
        self.translator.close()
        self.asr.close()

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3.0)

        logger.info("Pipeline stopped")

    def pause(self):
        self._paused.clear()
        logger.info("Pipeline paused")

    def resume(self):
        self._paused.set()
        self.vad.reset()
        logger.info("Pipeline resumed")

    def set_language(self, lang: str):
        self.asr.set_language(lang)
        logger.info("ASR language: %s", lang)

    def apply_config(self):
        cfg = reload_config()
        self.asr.set_language(cfg.asr.language)
        self.translator.target_language = cfg.translator.target_language
        logger.info("Config updated: ASR=%s, target=%s", cfg.asr.language, cfg.translator.target_language)

    def reset_context(self):
        self.translator.reset_context()
        self.vad.reset()

    # ── Async coroutines ──────────────────────────────

    async def _audio_feeder(self):
        """Read audio from capture device and feed to VAD processor."""
        logger.info("Audio feeder started")
        while self._running.is_set():
            await self._paused.wait()
            try:
                chunk = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.capture.read(timeout=0.5)
                )
                if chunk is None:
                    break
                if len(chunk) == 0:
                    continue
                # Process through VAD inline (simplifies data flow)
                speech_segments = self.vad.process_chunk(chunk)
                for segment in speech_segments:
                    try:
                        self._asr_queue.put_nowait(segment)
                    except asyncio.QueueFull:
                        logger.warning("ASR queue full, dropping segment")
            except Exception:
                logger.exception("Audio feeder error")
                await asyncio.sleep(0.5)
        logger.info("Audio feeder stopped")

    async def _vad_processor(self):
        """Placeholder — VAD is done inline in audio_feeder for simplicity."""
        # This coroutine exists for potential future separation
        while self._running.is_set():
            await asyncio.sleep(1.0)

    async def _asr_worker(self):
        """Transcribe speech segments to text."""
        logger.info("ASR worker started")
        while self._running.is_set():
            try:
                segment = await asyncio.wait_for(self._asr_queue.get(), timeout=1.0)
                if segment is None:
                    break

                await self._paused.wait()

                text = await self.asr.transcribe_async(segment)
                if not text:
                    continue

                try:
                    self._translate_queue.put_nowait(("normal", text))
                except asyncio.QueueFull:
                    logger.warning("Translate queue full, dropping: %s", text[:30])

            except asyncio.TimeoutError:
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

        self._translate_queue.put_nowait(None)
        logger.info("ASR worker stopped")

    async def _translate_worker(self):
        """Translate text and emit subtitles."""
        logger.info("Translate worker started")
        while self._running.is_set():
            try:
                item = await asyncio.wait_for(self._translate_queue.get(), timeout=1.0)
                if item is None:
                    break

                task_type, text = item

                await self._paused.wait()

                cfg = get_config()
                use_stream = cfg.display.stream_translation

                if task_type == "flush" or not use_stream:
                    translation = await self.translator.translate_async(text)
                    self._emit_subtitle(text, translation or "...")
                else:
                    await self._stream_translate(text)

            except asyncio.TimeoutError:
                continue
            except Exception:
                logger.exception("Translate worker error")
                await asyncio.sleep(0.5)

        logger.info("Translate worker stopped")

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
        logger.info("Subtitle: [orig] %s  [trans] %s", original, translation)
        if self._on_subtitle:
            try:
                self._on_subtitle(original, translation)
            except Exception:
                logger.exception("Subtitle callback error")
