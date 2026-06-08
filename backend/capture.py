"""
音频捕获 —— WASAPI 系统音频采集。

只使用 WASAPI hostapi（唯一支持回调模式的 hostapi）。
捕获系统音频（Loopback / Stereo Mix），不回退到麦克风。
"""

import threading
import queue
import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from .config import get_config

logger = logging.getLogger(__name__)


class AudioCapture:
    """系统音频采集器（仅 WASAPI hostapi，支持 Loopback / Stereo Mix）"""

    def __init__(self, device_id: Optional[int] = None):
        cfg = get_config()
        self.sample_rate = cfg.sample_rate
        self.block_size = int(self.sample_rate * 0.1)
        self.queue: queue.Queue[Optional[np.ndarray]] = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._running = False
        self._device_id = device_id
        self._actual_sr = cfg.sample_rate
        self._wasapi_idx: Optional[int] = None
        self._use_wasapi = False
        self._wasapi = None

    def _get_wasapi_hostapi(self) -> int:
        """获取 WASAPI hostapi 索引（缓存）"""
        if self._wasapi_idx is None:
            for i, api in enumerate(sd.query_hostapis()):
                if "wasapi" in api["name"].lower():
                    self._wasapi_idx = i
                    break
            if self._wasapi_idx is None:
                self._wasapi_idx = -1
        return self._wasapi_idx

    def _resolve_device(self) -> Optional[int]:
        """解析 WASAPI 下的系统音频设备（Loopback / Stereo Mix）"""
        cfg = get_config()
        wasapi = self._get_wasapi_hostapi()
        if wasapi < 0:
            logger.error("未找到 WASAPI hostapi，请检查 Windows 音频服务。")
            return None

        # 1. 显式指定
        if self._device_id is not None:
            d = sd.query_devices(self._device_id)
            if d["hostapi"] == wasapi:
                return self._device_id
            logger.warning("指定的设备 [%d] 不在 WASAPI 下，请选择 WASAPI 设备", self._device_id)

        # 2. 配置指定
        device_str = cfg.audio_device
        mic_kw = ["麦克风", "microphone", "mic ", " mic", "array", "headset"]
        if device_str and device_str != "auto":
            try:
                dev_id = int(device_str)
                d = sd.query_devices(dev_id)
                if d["hostapi"] == wasapi:
                    name = d["name"].lower()
                    if any(mk in name for mk in mic_kw):
                        logger.warning("配置的设备 [%d] %s 是麦克风，已跳过", dev_id, d["name"])
                    else:
                        logger.info("使用配置设备: [%d] %s", dev_id, d["name"])
                        return dev_id
                else:
                    logger.warning("配置的设备 [%d] 不在 WASAPI 下", dev_id)
            except (ValueError, sd.PortAudioError):
                logger.warning("配置的设备 '%s' 无效", device_str)

        # 3. 自动检测 WASAPI 下的 Loopback / Stereo Mix
        return self._find_system_audio(wasapi)

    def _find_system_audio(self, wasapi: int) -> Optional[int]:
        """
        在 WASAPI hostapi 下搜索系统音频设备。
        关键字：loopback / stereo mix / 立体声混音 / 立体声
        """
        try:
            devices = sd.query_devices()
            keywords = [
                "loopback", "立体声混音", "stereo mix",
                "stereo input", "立体声", "what u hear",
                "wave out mix", "streaming",
            ]

            mic_keywords = ["麦克风", "microphone", "mic ", " mic", "array", "headset"]
            for i, d in enumerate(devices):
                if d["hostapi"] != wasapi or d["max_input_channels"] <= 0:
                    continue
                name = d["name"].lower()
                # 跳过明显的麦克风
                if any(mk in name for mk in mic_keywords):
                    continue
                for kw in keywords:
                    if kw in name:
                        logger.info("找到系统音频: [%d] %s (WASAPI)", i, d["name"])
                        return int(i)

            # 未找到：列出所有 WASAPI 输入设备并给出指引
            logger.warning("=== WASAPI 下未找到系统音频设备（Loopback/立体声混音）===")
            inputs = [(i, d["name"]) for i, d in enumerate(devices)
                      if d["hostapi"] == wasapi and d["max_input_channels"] > 0]
            if inputs:
                logger.warning("WASAPI 输入设备（全部是麦克风）：")
                for idx, name in inputs:
                    logger.warning("  [%d] %s", idx, name)
            else:
                logger.warning("没有任何 WASAPI 输入设备。")

            logger.warning(
                "\n请手动启用立体声混音：\n"
                "  控制面板 → 声音 → 录制 → 右键 → 显示禁用的设备\n"
                "  → 找到「立体声混音」或「Stereo Mix」→ 右键 → 启用\n"
                "  启用后重启 Vocis。"
            )
            return None

        except Exception:
            logger.exception("枚举音频设备出错")
            return None

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        if status:
            logger.warning("音频回调状态: %s", status)
        if indata.ndim > 1:
            indata = indata.mean(axis=1)
        self.queue.put(indata.copy())

    def start(self) -> bool:
        """启动音频捕获（sounddevice 优先，失败则降级到 WASAPI Loopback）"""
        if self._running:
            return True

        # 策略 1：sounddevice + WASAPI 设备（Stereo Mix / Loopback）
        device = self._resolve_device()
        if device is not None:
            try:
                dev_info = sd.query_devices(device)
                sr = int(dev_info["default_samplerate"])
            except Exception:
                sr = self.sample_rate

            try:
                self._stream = sd.InputStream(
                    device=device,
                    channels=1,
                    samplerate=sr,
                    callback=self._audio_callback,
                    blocksize=int(sr * 0.1),
                    dtype="float32",
                )
                self._stream.start()
                self._actual_sr = sr
                self._running = True
                logger.info("音频采集已启动 (sounddevice, device=%d, sr=%d)", device, sr)
                return True
            except Exception as e:
                logger.warning("sounddevice 打开失败: %s", e)

        # 策略 2：WASAPI Loopback（无需 Stereo Mix）
        logger.info("降级到 WASAPI Loopback 模式（直接从扬声器抓取）")
        return self._start_wasapi_loopback()

    def _start_wasapi_loopback(self) -> bool:
        """启动 WASAPI Loopback 后端"""
        try:
            from .wasapi_loopback import WasapiLoopbackCapture

            self._wasapi = WasapiLoopbackCapture(sample_rate=self.sample_rate)
            if not self._wasapi.start():
                logger.error("WASAPI Loopback 启动失败")
                return False

            # 接管 read 方法
            self._running = True
            self._use_wasapi = True
            logger.info("音频采集已启动 (WASAPI Loopback, sr=%d)", self.sample_rate)
            return True
        except ImportError as e:
            logger.error("无法导入 wasapi_loopback 模块: %s", e)
            logger.error(
                "请检查：\n"
                "  1. 确保 backend/wasapi_loopback.py 文件存在\n"
                "  2. 确保已安装 comtypes: pip install comtypes"
            )
            return False
        except Exception as e:
            logger.exception("WASAPI Loopback 异常: %s", e)
            return False

    def stop(self):
        self._running = False
        if hasattr(self, "_use_wasapi") and self._use_wasapi:
            if hasattr(self, "_wasapi"):
                self._wasapi.stop()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.queue.put(None)
        logger.info("音频采集已停止")

    def read(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        if hasattr(self, "_use_wasapi") and self._use_wasapi:
            return self._wasapi.read(timeout=timeout)
        try:
            item = self.queue.get(timeout=timeout)
            if item is None:
                return None
            return item
        except queue.Empty:
            return np.array([], dtype=np.float32)

    def read_nonblocking(self) -> Optional[np.ndarray]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
