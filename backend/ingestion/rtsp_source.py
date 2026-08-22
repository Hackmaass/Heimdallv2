"""
RTSP Video Stream Ingestion (Drone / IP Camera)
"""

import time
import cv2
from typing import Optional, Generator, Tuple
from .base import VideoSource, FrameData


class RTSPSource(VideoSource):
    """
    RTSP / RTMP live stream ingestion from drone payload or edge camera.
    """

    def __init__(self, rtsp_url: str):
        self.rtsp_url = rtsp_url
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count = 0
        self._fps = 30.0
        self._start_time = 0.0

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self.rtsp_url)
        if not self._cap.isOpened():
            raise ConnectionError(f"Cannot connect to RTSP stream: {self.rtsp_url}")
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._start_time = time.time()
        self._frame_count = 0
        return True

    def read_frame(self) -> Optional[FrameData]:
        if self._cap is None:
            self.open()

        ret, frame = self._cap.read()
        if not ret or frame is None:
            return None

        h, w = frame.shape[:2]
        timestamp = time.time() - self._start_time
        frame_idx = self._frame_count
        self._frame_count += 1

        return FrameData(
            frame_index=frame_idx,
            timestamp_seconds=timestamp,
            frame=frame,
            width=w,
            height=h,
            fps=self._fps,
            is_last=False,
        )

    def frames(self) -> Generator[FrameData, None, None]:
        while True:
            frame_data = self.read_frame()
            if frame_data is None:
                break
            yield frame_data

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def total_frames(self) -> int:
        return -1  # Live stream

    @property
    def resolution(self) -> Tuple[int, int]:
        if self._cap:
            return (
                int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
        return (0, 0)
