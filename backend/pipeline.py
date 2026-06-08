"""
主流水线 —— 串联音频捕获 → VAD → ASR → 翻译 → GUI。

使用回调模式将字幕事件推送到 GUI 层。
"""

import logging
import threading
import time
from typing import Callable, Optional

from .capture import AudioCapture
from .vad import VoiceActivityDetector
from .asr import create_asr
from .translator import DeepSeekTranslator
from .config import get_config

logger = logging.getLogger(__name__)


class SubtitlePipeline:
    """
    屏幕字幕主流水线。

    循环：音频捕获 → VAD 切句 → ASR 识别 → 翻译 → 输出
    """

    def __init__(self):
        cfg = get_config()
        self.capture = AudioCapture()
        self.vad = VoiceActivityDetector()
        self.asr = create_asr()
        self.translator = DeepSeekTranslator()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_subtitle: Optional[Callable[[str, str], None]] = None
        self._paused = False
        self._pending_lang: Optional[str] = None

    def on_subtitle(self, callback: Callable[[str, str], None]):
        """注册字幕回调：callback(original, translation)"""
        self._on_subtitle = callback

    def start(self) -> bool:
        """启动流水线"""
        if not self.capture.start():
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("流水线已启动")
        return True

    def stop(self):
        """停止流水线"""
        self._running = False
        self.capture.stop()
        self.translator.close()
        self.asr.close()
        logger.info("流水线已停止")

    def pause(self):
        self._paused = True
        logger.info("流水线已暂停")

    def resume(self):
        self._paused = False
        self.vad.reset()  # 恢复时重置 VAD，丢弃暂停期间积累的残留
        logger.info("流水线已恢复")

    def set_language(self, lang: str):
        """运行时切换 ASR 识别语言"""
        self.asr.set_language(lang)
        logger.info("ASR 语言切换: %s", lang)

    def reset_context(self):
        """重置翻译上下文（切换视频时）"""
        self.translator.reset_context()
        self.vad.reset()

    def _run_loop(self):
        """主循环（运行在后台线程）"""
        logger.info("流水线主循环开始")

        while self._running:
            try:
                # 1. 读取音频块
                chunk = self.capture.read(timeout=0.5)
                if chunk is None:
                    break  # 停止信号
                if len(chunk) == 0:
                    continue  # 超时，无数据

                if self._paused:
                    # 暂停时丢弃音频块，不处理
                    continue

                # 2. VAD 切句
                speech_segments = self.vad.process_chunk(chunk)

                for pcm_bytes in speech_segments:
                    # 3. ASR 识别
                    text = self.asr.transcribe(pcm_bytes)
                    if not text:
                        continue

                    # 4. 翻译
                    translation = self.translator.translate(text)
                    if not translation:
                        # 翻译失败也显示原文
                        self._emit_subtitle(text, "...")
                        continue

                    # 5. 输出字幕
                    self._emit_subtitle(text, translation)

            except Exception:
                logger.exception("流水线循环异常")
                time.sleep(0.5)

        # 循环结束，刷新 VAD 中残留的语音段
        self._flush_remaining()

    def _flush_remaining(self):
        """刷新流水线停止时残留的语音段"""
        segments = self.vad.flush()
        for pcm_bytes in segments:
            text = self.asr.transcribe(pcm_bytes)
            if text:
                translation = self.translator.translate(text)
                self._emit_subtitle(text, translation or "...")

    def _emit_subtitle(self, original: str, translation: str):
        """发送字幕事件到 GUI"""
        logger.info("字幕: [原文] %s  [译文] %s", original, translation)
        if self._on_subtitle:
            try:
                self._on_subtitle(original, translation)
            except Exception:
                logger.exception("字幕回调异常")
