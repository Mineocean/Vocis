"""
ASR 语音识别 —— 多后端架构。

后端选择通过 ASR_BACKEND 环境变量控制：
  - mimo：  MiMo-V2.5-ASR 云端 API
  - whisper：本地 faster-whisper 模型（需 pip install faster-whisper）
  - mock：  模拟文本，用于测试翻译/GUI 链路
"""

import base64
import io
import logging
import wave
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from .config import get_config

logger = logging.getLogger(__name__)


# ── 工具函数 ──────────────────────────────────────────

def pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    """将原始 PCM 数据封装为 WAV 格式"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# ── 抽象基类 ──────────────────────────────────────────

class ASREngine(ABC):
    """ASR 引擎抽象基类"""

    @abstractmethod
    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        """将 PCM 音频转为文本"""
        ...

    def set_language(self, language: str):
        """运行时切换识别语言（子类可覆盖）"""
        pass

    def close(self):
        """释放资源（子类可覆盖）"""
        pass


# ── MiMo 云端后端 ─────────────────────────────────────

class MiMoASR(ASREngine):
    """MiMo-V2.5-ASR 云端 API"""

    def __init__(self):
        cfg = get_config()
        self.api_key = cfg.asr.api_key
        self.language = cfg.asr.language
        self.model = cfg.asr.model
        self._client: Optional[httpx.Client] = None

        # URL 规范化
        base = cfg.asr.base_url.rstrip("/")
        if not base.endswith("/v1"):
            if "/v1/" in base or "/v1" in base:
                idx = base.index("/v1")
                base = base[:idx + 3]
            else:
                base += "/v1"
        self.base_url = base

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def set_language(self, language: str):
        self.language = language

    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        if not audio_pcm:
            return None

        wav_data = pcm_to_wav(audio_pcm, sample_rate=16000)
        audio_b64 = base64.b64encode(wav_data).decode("ascii")
        data_url = f"data:audio/wav;base64,{audio_b64}"

        body: dict = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data_url},
                        }
                    ],
                }
            ],
            "asr_options": {"language": self.language},
        }

        try:
            resp = self.client.post("/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if text:
                logger.info("MiMo ASR: %s", text)
                return text.strip()
            logger.warning("MiMo ASR 返回空文本")
            return None
        except httpx.HTTPStatusError as e:
            logger.error("MiMo HTTP %d: %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            logger.error("MiMo 请求异常: %s", e)
            return None

    def close(self):
        if self._client:
            self._client.close()
            self._client = None


# ── Whisper 本地后端 ──────────────────────────────────

class WhisperASR(ASREngine):
    """本地 faster-whisper 模型（支持 NVIDIA GPU 加速）"""

    def __init__(self, model_size: str = "tiny", device: str = "cuda"):
        self._model = None
        self._model_size = model_size
        self._device = device
        self._language: Optional[str] = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            # 检测 GPU 可用性
            device = self._device
            compute = "int8"
            if device in ("cuda", "auto"):
                try:
                    import torch
                    if torch.cuda.is_available():
                        compute = "float16"
                        device = "cuda"
                        logger.info("使用 CUDA GPU 加速 (float16)")
                    elif device == "cuda":
                        logger.warning("CUDA 不可用，回退到 CPU——请安装 CUDA 版 PyTorch")
                        device = "cpu"
                    else:
                        logger.info("CUDA 不可用，使用 CPU")
                        device = "cpu"
                except ImportError:
                    logger.warning("torch 未安装，回退到 CPU")
                    device = "cpu"

            logger.info("加载 Whisper 模型: %s (device=%s, compute=%s)",
                        self._model_size, device, compute)
            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute,
            )
            logger.info("Whisper 模型加载完成")
        except ImportError:
            raise ImportError(
                "使用 WHISPER 后端需安装 faster-whisper:\n"
                "  pip install faster-whisper"
            )
        except Exception as e:
            logger.error("加载 Whisper 模型失败: %s", e)
            raise

    def set_language(self, language: str):
        self._language = None if language == "auto" else language

    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        if not audio_pcm:
            return None

        self._load_model()

        import numpy as np

        # PCM int16 → float32 归一化
        audio_np = np.frombuffer(audio_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        # 截断过长音频（CPU 上处理 >15s 太慢）
        max_samples = 16000 * 15  # 15 秒 @ 16kHz
        if len(audio_np) > max_samples:
            logger.debug("音频过长 (%d samples)，截断到 %d", len(audio_np), max_samples)
            audio_np = audio_np[:max_samples]

        try:
            segments, info = self._model.transcribe(
                audio_np,
                language=self._language,
                beam_size=1,         # 最快模式
                vad_filter=False,    # 外部已有 VAD，关掉内部
            )
            text = " ".join(seg.text.strip() for seg in segments)
            if text:
                logger.info("Whisper ASR: %s", text)
                return text
            return None
        except Exception as e:
            logger.error("Whisper 识别失败: %s", e)
            return None

    def close(self):
        self._model = None


# ── Mock 后端（测试用）─────────────────────────────────

class MockASR(ASREngine):
    """模拟 ASR——用于测试翻译和 GUI 链路，不调用任何 API"""

    _counter = 0
    _mock_texts = [
        "Hello, how are you today?",
        "The weather is beautiful outside.",
        "I think artificial intelligence is fascinating.",
        "What time does the meeting start tomorrow?",
        "Could you please pass me the salt?",
        "This is a test of the emergency broadcast system.",
        "Machine learning has changed the world dramatically.",
        "Let's grab some coffee after work.",
    ]

    def transcribe(self, audio_pcm: bytes) -> Optional[str]:
        if not audio_pcm:
            return None
        text = self._mock_texts[self._counter % len(self._mock_texts)]
        MockASR._counter += 1
        logger.info("Mock ASR: %s", text)
        return text


# ── 工厂函数 ──────────────────────────────────────────

def create_asr() -> ASREngine:
    """根据配置创建 ASR 引擎实例"""
    cfg = get_config()
    backend = cfg.asr.backend.lower()

    if backend == "mimo":
        return MiMoASR()
    elif backend == "whisper":
        return WhisperASR(
            model_size=cfg.asr.whisper_model,
            device=cfg.asr.whisper_device,
        )
    elif backend == "mock":
        return MockASR()
    else:
        logger.warning("未知 ASR 后端 '%s'，回退到 mock", backend)
        return MockASR()
