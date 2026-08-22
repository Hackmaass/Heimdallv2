"""
Video Ingestion Base Interfaces
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Generator, Tuple
import numpy as np


@dataclass
class FrameData:
    """Standardized video frame container."""
    frame_index: int
    timestamp_seconds: float
    frame: np.ndarray  # BGR image array
    width: int
    height: int
    fps: float
    is_last: bool = False


class VideoSource(ABC):
    """Abstract base class for all video sources (Files, RTSP, WebRTC)."""

    @abstractmethod
    def open(self) -> bool:
        """Opens video stream/file."""
        pass

    @abstractmethod
    def read_frame(self) -> Optional[FrameData]:
        """Reads the next video frame."""
        pass

    @abstractmethod
    def frames(self) -> Generator[FrameData, None, None]:
        """Generator yielding frames sequentially."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Releases underlying resources."""
        pass

    @property
    @abstractmethod
    def fps(self) -> float:
        pass

    @property
    @abstractmethod
    def total_frames(self) -> int:
        pass

    @property
    @abstractmethod
    def resolution(self) -> Tuple[int, int]:
        """(width, height)"""
        pass

    @property
    def width(self) -> int:
        return self.resolution[0]

    @property
    def height(self) -> int:
        return self.resolution[1]

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
