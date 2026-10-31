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


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("Samples", wintypes.WORD),
        ("dwChannelMask", wintypes.DWORD),
        ("SubFormat", GUID),
    ]


KSDATAFORMAT_SUBTYPE_PCM = "{00000001-0000-0010-8000-00AA00389B71}"
KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = "{00000003-0000-0010-8000-00AA00389B71}"


def _guid_equal(guid: GUID, text: str) -> bool:
    ref = guid_from_str(text)
    return (
        guid.Data1 == ref.Data1
        and guid.Data2 == ref.Data2
        and guid.Data3 == ref.Data3
        and bytes(guid.Data4) == bytes(ref.Data4)
    )


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

            # 4. GetMixFormat (vtable[8])：共享模式必须使用设备混音格式，
            #    硬编码 48k/16bit 会得到 AUDCLNT_E_UNSUPPORTED_FORMAT。
            get_mix = _make_func(pAudioClient, 8, ctypes.c_long,
                                 ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)))
            pMix = ctypes.POINTER(WAVEFORMATEX)()
            hr = get_mix(pAudioClient, ctypes.byref(pMix))
            if hr != 0 or not pMix:
                logger.error(f"GetMixFormat 失败: 0x{hr:08X}")
                return

            fmt = pMix.contents
            self._actual_sr = int(fmt.nSamplesPerSec)
            self._actual_channels = max(1, int(fmt.nChannels))
            sample_bytes = max(1, int(fmt.nBlockAlign) // self._actual_channels)
            self._is_float = fmt.wFormatTag == 3
            if fmt.wFormatTag == 0xFFFE:
                ext = ctypes.cast(pMix, ctypes.POINTER(WAVEFORMATEXTENSIBLE)).contents
                self._is_float = _guid_equal(ext.SubFormat, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)
                if not self._is_float and not _guid_equal(ext.SubFormat, KSDATAFORMAT_SUBTYPE_PCM):
                    logger.warning("未知混音格式子类型，按 PCM 处理")
            self._container_bytes = sample_bytes
            self._actual_bits = sample_bytes * 8
            logger.info(
                "设备混音格式: %dHz, %dch, %d-bit %s",
                self._actual_sr, self._actual_channels, self._actual_bits,
                "float" if self._is_float else "pcm",
            )

            init = _make_func(pAudioClient, 3, ctypes.c_long,
                              ctypes.c_int, ctypes.c_uint, ctypes.c_longlong,
                              ctypes.c_longlong, ctypes.POINTER(WAVEFORMATEX),
                              ctypes.c_void_p)
            hr = init(pAudioClient, AUDCLNT_SHAREMODE_SHARED,
                      AUDCLNT_STREAMFLAGS_LOOPBACK, 0, 0, pMix, None)
            ole32.CoTaskMemFree(pMix)
            if hr != 0:
                logger.error(f"Initialize 失败: 0x{hr:08X}")
                return

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
            frame_bytes = self._actual_channels * self._container_bytes
            target_bytes = int(self._actual_sr * 0.1) * frame_bytes

            while self._running.is_set():
                try:
                    buf_ptr = ctypes.POINTER(ctypes.c_ubyte)()
                    num_frames = wintypes.UINT()
                    flags = wintypes.DWORD()
                    hr = get_buf(pCaptureClient, ctypes.byref(buf_ptr),
                                 ctypes.byref(num_frames), ctypes.byref(flags),
                                 None, None)

                    if hr == 0 and num_frames.value > 0:
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
        """Device mix format → mono 16kHz float32 (scipy resample_poly)."""
        try:
            from scipy.signal import resample_poly

            width = getattr(self, "_container_bytes", 2)
            count = len(raw) // width
            if count <= 0:
                return None
            if self._is_float:
                if width == 4:
                    audio = np.frombuffer(raw, dtype=np.float32, count=count)
                elif width == 8:
                    audio = np.frombuffer(raw, dtype=np.float64, count=count).astype(np.float32)
                else:
                    return None
            elif width == 2:
                audio = np.frombuffer(raw, dtype=np.int16, count=count).astype(np.float32) / 32768.0
            elif width == 3:
                b = np.frombuffer(raw, dtype=np.uint8, count=count * 3).reshape(-1, 3).astype(np.int32)
                v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
                v = np.where(v >= (1 << 23), v - (1 << 24), v)
                audio = v.astype(np.float32) / float(1 << 23)
            elif width == 4:
                audio = np.frombuffer(raw, dtype=np.int32, count=count).astype(np.float32) / float(1 << 31)
            else:
                return None

            if self._actual_channels > 1:
                audio = audio.reshape(-1, self._actual_channels).mean(axis=1)

            if self._actual_sr != self.sample_rate:
                from math import gcd
                g = gcd(int(self._actual_sr), self.sample_rate)
                up = self.sample_rate // g
                down = int(self._actual_sr) // g
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
