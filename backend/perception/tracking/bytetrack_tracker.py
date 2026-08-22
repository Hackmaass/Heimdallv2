"""
ByteTrack Multi-Object Tracker Implementation
High-speed alternative tracker for fixed/stable camera angles
"""

import math
import os
from typing import Dict, List
import numpy as np
from ultralytics import YOLO

from .base import BaseTracker, TrackedObject, TrackingResult
from ..classification.taxonomy import normalize_class


class ByteTrackTracker(BaseTracker):
    """
    ByteTrack Multi-Object Tracker.
    High-speed association using both high and low confidence detection bounding boxes.
    """

    def __init__(
        self,
        model_name_or_path: str = "yolov8n.pt",
        config_path: str = "configs/bytetrack.yaml",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
    ):
        self.model_name_or_path = model_name_or_path
        self.config_path = config_path
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.img_size = img_size
        self.device = device

        self.model = YOLO(self.model_name_or_path)
        self._prev_centroids: Dict[int, tuple] = {}
        self._prev_timestamps: Dict[int, float] = {}
        self._first_seen: Dict[int, float] = {}
        self._frame_counts: Dict[int, int] = {}

    def update(
        self,
        frame: np.ndarray,
        frame_index: int,
        timestamp: float,
    ) -> TrackingResult:
        # Resolve compute device
        track_device = self.device
        if track_device == "auto":
            try:
                import torch
                track_device = 0 if torch.cuda.is_available() else "cpu"
            except Exception:
                track_device = "cpu"

        results = self.model.track(
            source=frame,
            persist=True,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            imgsz=self.img_size,
            tracker="bytetrack.yaml",
            device=track_device,
            verbose=False,
        )

        active_tracks: List[TrackedObject] = []

        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes
            if boxes is not None:
                for i in range(len(boxes)):
                    box = boxes[i]
                    if box.id is None:
                        continue

                    track_id = int(box.id[0].item())
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    raw_name = self.model.names.get(cls_id, f"class_{cls_id}")

                    xyxy = box.xyxy[0].tolist()
                    x1, y1, x2, y2 = [float(v) for v in xyxy]
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    normalized = normalize_class(raw_name, conf, [x1, y1, x2, y2])

                    if track_id not in self._first_seen:
                        self._first_seen[track_id] = timestamp
                        self._frame_counts[track_id] = 0
                    self._frame_counts[track_id] += 1

                    vx, vy = 0.0, 0.0
                    speed_px_s = 0.0
                    heading_deg = 0.0
                    is_stationary = False

                    if track_id in self._prev_centroids:
                        prev_cx, prev_cy = self._prev_centroids[track_id]
                        prev_t = self._prev_timestamps.get(track_id, timestamp - 0.033)
                        dt = max(0.001, timestamp - prev_t)

                        dx = cx - prev_cx
                        dy = cy - prev_cy
                        vx = dx / dt
                        vy = dy / dt
                        dist = math.hypot(dx, dy)
                        speed_px_s = dist / dt

                        if dist > 1.0:
                            rad = math.atan2(dy, dx)
                            heading_deg = (math.degrees(rad) + 360.0) % 360.0

                        if speed_px_s < 3.0:
                            is_stationary = True

                    self._prev_centroids[track_id] = (cx, cy)
                    self._prev_timestamps[track_id] = timestamp

                    active_tracks.append(
                        TrackedObject(
                            track_id=track_id,
                            raw_class=raw_name,
                            normalized=normalized,
                            confidence=conf,
                            bbox=[x1, y1, x2, y2],
                            centroid=(cx, cy),
                            velocity=(vx, vy),
                            speed_estimate=round(speed_px_s, 2),
                            heading=round(heading_deg, 1),
                            is_stationary=is_stationary,
                            first_seen_timestamp=self._first_seen[track_id],
                            last_seen_timestamp=timestamp,
                            frame_count=self._frame_counts[track_id],
                        )
                    )

        return TrackingResult(
            frame_index=frame_index,
            timestamp=timestamp,
            tracks=active_tracks,
            active_count=len(active_tracks),
        )

    def reset(self) -> None:
        self._prev_centroids.clear()
        self._prev_timestamps.clear()
        self._first_seen.clear()
        self._frame_counts.clear()
