"""
File-based Video Source Implementation (OpenCV / FFmpeg)
"""

import os
import cv2
from typing import Optional, Generator, Tuple
import numpy as np
from .base import VideoSource, FrameData


class FileSource(VideoSource):
    """
    Video ingestion from a local video file (MP4, AVI, MKV, MOV).
    """

    def __init__(
        self,
        file_path: str,
        loop: bool = False,
        start_frame: int = 0,
        max_frames: Optional[int] = None,
    ):
        self.file_path = file_path
        self.loop = loop
        self.start_frame = start_frame
        self.max_frames = max_frames

        self._cap: Optional[cv2.VideoCapture] = None
        self._current_frame_idx = 0
        self._fps = 30.0
        self._total_frames = 0
        self._width = 0
        self._height = 0

    def open(self) -> bool:
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Video file not found: {self.file_path}")

        self._cap = cv2.VideoCapture(self.file_path)
        if not self._cap.isOpened():
            raise RuntimeError(f"OpenCV failed to open video: {self.file_path}")

        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0

        if self.start_frame > 0:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
            self._current_frame_idx = self.start_frame
        else:
            self._current_frame_idx = 0

        return True

    def read_frame(self) -> Optional[FrameData]:
        if self._cap is None:
            self.open()

        if self.max_frames and self._current_frame_idx >= (self.start_frame + self.max_frames):
            return None

        ret, frame = self._cap.read()

        if not ret or frame is None:
            if self.loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
                self._current_frame_idx = self.start_frame
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    return None
            else:
                return None

        frame_idx = self._current_frame_idx
        timestamp = frame_idx / self._fps
        self._current_frame_idx += 1

        is_last = ((self._current_frame_idx >= self._total_frames) or (bool(self.max_frames) and self._current_frame_idx >= (self.start_frame + self.max_frames))) and not self.loop

        return FrameData(
            frame_index=frame_idx,
            timestamp_seconds=timestamp,
            frame=frame,
            width=self._width,
            height=self._height,
            fps=self._fps,
            is_last=is_last,
        )

    def frames(self) -> Generator[FrameData, None, None]:
        while True:
            frame_data = self.read_frame()
            if frame_data is None:
                break
            yield frame_data
            if frame_data.is_last:
                break

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def total_frames(self) -> int:
        if self.max_frames and self.max_frames > 0:
            if self._total_frames > 0:
                available = max(0, self._total_frames - self.start_frame)
                return min(available, self.max_frames)
            return self.max_frames
        return self._total_frames

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self._width, self._height)
