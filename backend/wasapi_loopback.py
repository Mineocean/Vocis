"""
Windows WASAPI Loopback 音频捕获 —— 纯 ctypes 实现。

直接从扬声器输出设备抓取系统音频，无需 Stereo Mix。
Windows 10/11 原生支持，零第三方编译依赖。
"""

import ctypes
import logging
import queue
import threading
from ctypes import wintypes

import numpy as np

logger = logging.getLogger(__name__)

# ── GUID 结构体 ───────────────────────────────────────

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


def guid_from_str(s: str) -> GUID:
    """从字符串创建 GUID"""
    from ctypes import oledll
    g = GUID()
    oledll.ole32.CLSIDFromString(s, ctypes.byref(g))
    return g


# ── COM 常量 ──────────────────────────────────────────

CLSCTX_INPROC_SERVER = 1
CLSCTX_ALL = 23

# ── WAVEFORMATEX ──────────────────────────────────────

class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


# ── WASAPI 常量 ───────────────────────────────────────

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_E_UNSUPPORTED_FORMAT = 0x88890008

eRender = 0
# AudioDeviceCategory：eConsole=0 / eMultimedia=1 / eCommunications=2
# 必须用 eMultimedia(1)，否则播放器/浏览器的多媒体会话声音抓不到。
eMultimedia = 1

# GUIDs
CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioClient = "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"
IID_IAudioCaptureClient = "{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"


# ── 主捕获器 ──────────────────────────────────────────

class WasapiLoopbackCapture:
    """Windows WASAPI Loopback 音频捕获（纯 ctypes，零依赖）"""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=50)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._actual_sr = sample_rate
        self._actual_channels = 2
        self._actual_bits = 16
        self._is_float = False

    def start(self) -> bool:
        if self._running.is_set():
            return True
        self._running.set()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running.clear()
        self.queue.put(None)

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            item = self.queue.get(timeout=timeout)
            if item is None:
                return None
            return item
        except queue.Empty:
            return np.array([], dtype=np.float32)

    def flush(self):
        """清空队列中积压的音频数据（暂停恢复时调用）。"""
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _capture_loop(self):
        """主捕获循环"""
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)

        try:
            # 1. 创建 MMDeviceEnumerator
            clsid = guid_from_str(CLSID_MMDeviceEnumerator)
            iid_enum = guid_from_str(IID_IMMDeviceEnumerator)
            pEnumerator = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid), None, CLSCTX_ALL,
                ctypes.byref(iid_enum), ctypes.byref(pEnumerator)
            )
            if hr != 0:
                logger.error(f"CoCreateInstance MMDeviceEnumerator 失败: 0x{hr:08X}")
                return

            # 2. GetDefaultAudioEndpoint (vtable[4])
            pDevice = ctypes.c_void_p()
            getDef = _make_func(pEnumerator, 4, ctypes.c_long,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_void_p))
            hr = getDef(pEnumerator, eRender, eMultimedia, ctypes.byref(pDevice))
            if hr != 0:
                logger.error(f"GetDefaultAudioEndpoint 失败: 0x{hr:08X}")
                return

            # 3. Activate IAudioClient (vtable[3])
            iid_ac = guid_from_str(IID_IAudioClient)
            pAudioClient = ctypes.c_void_p()
            act = _make_func(pDevice, 3, ctypes.c_long, ctypes.POINTER(GUID),
                             ctypes.c_uint, ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_void_p))
            hr = act(pDevice, ctypes.byref(iid_ac), CLSCTX_INPROC_SERVER, None,
                     ctypes.byref(pAudioClient))
            if hr != 0:
                logger.error(f"Activate IAudioClient 失败: 0x{hr:08X}")
                return

            # 4. Initialize (vtable[3])
            wfx = WAVEFORMATEX()
            wfx.wFormatTag = 1   # PCM
            wfx.nChannels = 2
            wfx.nSamplesPerSec = 48000
            wfx.wBitsPerSample = 16
            wfx.nBlockAlign = wfx.nChannels * wfx.wBitsPerSample // 8
            wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign
            wfx.cbSize = 0

            init = _make_func(pAudioClient, 3, ctypes.c_long,
                              ctypes.c_int, ctypes.c_uint, ctypes.c_longlong,
                              ctypes.c_longlong, ctypes.POINTER(WAVEFORMATEX),
                              ctypes.c_void_p)
            hr = init(pAudioClient, AUDCLNT_SHAREMODE_SHARED,
                      AUDCLNT_STREAMFLAGS_LOOPBACK, 0, 0,
                      ctypes.byref(wfx), None)
            if hr != 0:
                # 降级尝试 float 格式
                wfx.wFormatTag = 3
                wfx.wBitsPerSample = 32
                wfx.nBlockAlign = wfx.nChannels * wfx.wBitsPerSample // 8
                wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign
                hr = init(pAudioClient, AUDCLNT_SHAREMODE_SHARED,
                          AUDCLNT_STREAMFLAGS_LOOPBACK, 0, 0,
                          ctypes.byref(wfx), None)
                if hr != 0:
                    logger.error(f"Initialize 失败: 0x{hr:08X}")
                    return
                self._is_float = True

            self._actual_sr = wfx.nSamplesPerSec
            self._actual_channels = wfx.nChannels
            self._actual_bits = wfx.wBitsPerSample

            # 5. GetService IAudioCaptureClient (vtable[14])
            iid_cc = guid_from_str(IID_IAudioCaptureClient)
            pCaptureClient = ctypes.c_void_p()
            gs = _make_func(pAudioClient, 14, ctypes.c_long,
                            ctypes.POINTER(GUID),
                            ctypes.POINTER(ctypes.c_void_p))
            hr = gs(pAudioClient, ctypes.byref(iid_cc), ctypes.byref(pCaptureClient))
            if hr != 0:
                logger.error(f"GetService 失败: 0x{hr:08X}")
                return

            # 6. Start (vtable[10])
            start_fn = _make_func(pAudioClient, 10, ctypes.c_long)
            hr = start_fn(pAudioClient)
            if hr != 0:
                logger.error(f"Start 失败: 0x{hr:08X}")
                return

            logger.info("WASAPI Loopback 已启动 (%dHz, %dch, %s)",
                        self._actual_sr, self._actual_channels,
                        "float32" if self._is_float else "int16")

            # 7. 捕获循环
            get_buf = _make_func(pCaptureClient, 3, ctypes.c_long,
                                 ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
                                 ctypes.POINTER(wintypes.UINT),
                                 ctypes.POINTER(wintypes.DWORD),
                                 ctypes.POINTER(ctypes.c_ulonglong),
                                 ctypes.POINTER(ctypes.c_ulonglong))
            release_buf = _make_func(pCaptureClient, 4, ctypes.c_long, wintypes.UINT)

            accumulated = bytearray()
            target_bytes = int(self._actual_sr * self._actual_channels * self._actual_bits // 8 * 0.1)

            while self._running.is_set():
                try:
                    buf_ptr = ctypes.POINTER(ctypes.c_ubyte)()
                    num_frames = wintypes.UINT()
                    flags = wintypes.DWORD()
                    hr = get_buf(pCaptureClient, ctypes.byref(buf_ptr),
                                 ctypes.byref(num_frames), ctypes.byref(flags),
                                 None, None)

                    if hr == 0 and num_frames.value > 0:
                        frame_bytes = self._actual_channels * self._actual_bits // 8
                        data_len = num_frames.value * frame_bytes
                        data = ctypes.string_at(buf_ptr, data_len)
                        accumulated.extend(data)
                        release_buf(pCaptureClient, num_frames.value)

                    while len(accumulated) >= target_bytes:
                        chunk = bytes(accumulated[:target_bytes])
                        accumulated = accumulated[target_bytes:]
                        audio_np = self._convert(chunk)
                        if audio_np is not None:
                            try:
                                self.queue.put_nowait(audio_np)
                            except queue.Full:
                                # 队列满：丢弃最旧的数据，防止暂停期间内存膨胀
                                try:
                                    self.queue.get_nowait()
                                except queue.Empty:
                                    pass

                except Exception as e:
                    logger.warning("WASAPI 捕获循环异常: %s", e)
                    break

        except Exception:
            logger.exception("WASAPI 捕获异常")
        finally:
            self._running.clear()
            self.queue.put(None)  # 通知上层停止
            ole32.CoUninitialize()

    def _convert(self, raw: bytes) -> np.ndarray | None:
        """Stereo 48kHz → Mono 16kHz float32 using scipy resample_poly."""
        try:
            from scipy.signal import resample_poly

            dtype = np.float32 if self._is_float else np.int16
            audio = np.frombuffer(raw, dtype=dtype)

            if self._actual_channels == 2:
                audio = audio.reshape(-1, 2).mean(axis=1)

            if not self._is_float:
                audio = audio.astype(np.float32) / 32768.0

            if self._actual_sr != self.sample_rate:
                from math import gcd
                g = gcd(self._actual_sr, self.sample_rate)
                up = self.sample_rate // g
                down = self._actual_sr // g
                audio = resample_poly(audio, up, down).astype(np.float32)

            return audio.astype(np.float32)
        except Exception as e:
            logger.warning("Audio conversion error: %s", e)
            return None


# ── vtable 辅助函数 ───────────────────────────────────

def _make_func(this: ctypes.c_void_p, idx: int, restype, *argtypes):
    """从 vtable[idx] 创建 CFUNCTYPE 包装函数"""
    pvtable = ctypes.cast(this, ctypes.POINTER(ctypes.c_void_p))
    pvtable = ctypes.cast(pvtable.contents, ctypes.POINTER(ctypes.c_void_p))
    func_ptr = pvtable[idx]
    all_types = [ctypes.c_void_p] + list(argtypes)
    proto = ctypes.WINFUNCTYPE(restype, *all_types)
    return proto(func_ptr)
