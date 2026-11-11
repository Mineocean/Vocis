"""Speaker identification contracts.

Diarization here is online: every VAD segment is embedded and assigned to a
speaker cluster, so subtitles can be tagged `Speaker 1/2/3...` as they appear.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

# 字幕里说话人配色槽位（UI 按 color_index 取色）
SPEAKER_COLOR_COUNT = 6


@dataclass(frozen=True)
class Speaker:
    """A stable speaker identity within one session. index is 1-based."""

    index: int

    @property
    def id(self) -> str:
        return f"S{self.index}"

    @property
    def color_index(self) -> int:
        return (self.index - 1) % SPEAKER_COLOR_COUNT


class SpeakerDiarizer(ABC):
    """Assign a speaker to a speech segment (online clustering)."""

    @abstractmethod
    def assign(self, audio_pcm: bytes) -> Speaker | None:
        """Return the speaker for this int16 16kHz mono segment.

        None means "not confident enough yet" (short audio before any speaker
        has been seen); callers should then emit the subtitle without a label.
        """
        ...

    async def assign_async(self, audio_pcm: bytes) -> Speaker | None:
        """Async wrapper so embedding work stays off the event loop.

        The tracker is entered/left inside the worker thread: cancelling the
        awaiting Task does not prove the embedding call has stopped.
        """
        tracker = getattr(self, "_work_tracker", None)
        if tracker is None:
            return await asyncio.to_thread(self.assign, audio_pcm)

        def run() -> Speaker | None:
            tracker.begin()
            try:
                return self.assign(audio_pcm)
            finally:
                tracker.end()

        return await asyncio.to_thread(run)

    def reset(self):
        """Forget all speakers (new video / context reset)."""

    def close(self):
        """Release resources."""
