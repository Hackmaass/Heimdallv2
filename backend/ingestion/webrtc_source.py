"""
WebRTC Stream Ingestion Abstraction
"""

from typing import Optional, Generator, Tuple
from .base import VideoSource, FrameData


class WebRTCSource(VideoSource):
    """
    WebRTC streaming source abstraction for ultra-low-latency drone video downlink.
    """

    def __init__(self, signaling_url: str, channel: str = "drone_live"):
        self.signaling_url = signaling_url
        self.channel = channel
        self._is_open = False
        self._frame_count = 0

    def open(self) -> bool:
        self._is_open = True
        self._frame_count = 0
        return True

    def read_frame(self) -> Optional[FrameData]:
        # Abstraction ready for aiortc integration in future stages
        return None

    def frames(self) -> Generator[FrameData, None, None]:
        while self._is_open:
            f = self.read_frame()
            if f is None:
                break
            yield f

    def close(self) -> None:
        self._is_open = False

    @property
    def fps(self) -> float:
        return 30.0

    @property
    def total_frames(self) -> int:
        return -1

    @property
    def resolution(self) -> Tuple[int, int]:
        return (1920, 1080)
