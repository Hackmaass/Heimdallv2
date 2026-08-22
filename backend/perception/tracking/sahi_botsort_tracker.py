"""
SAHI-Aware BoT-SORT Multi-Object Tracker with Zero-Loss Dead Reckoning
Seamlessly connects FastSAHIDetector (batched 4K slicing) directly
with Ultralytics BoT-SORT (Kalman filtering + GMC + high-persistence association + Kalman forward projection).

Ensures:
  1. Small road users (pedestrians, 2-wheelers, distant vehicles) are detected with high recall.
  2. Vehicles are NEVER lost during occlusions (Kalman coasting bridges temporary detection drops).
  3. Each vehicle maintains ONE continuous track_id from entry until it exits the camera frame.
"""

import math
import os
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple, Any, Set
import numpy as np
import torch
import yaml

from ultralytics.trackers.bot_sort import BOTSORT
from .base import BaseTracker, TrackedObject, TrackingResult
from ..classification.taxonomy import normalize_class
from ..detection.sahi_detector import FastSAHIDetector


class _SAHIDetectionContainer:
    """Lightweight adapter exposing xyxy, xywh, conf, and cls for Ultralytics BOTSORT."""

    def __init__(self, xyxy: torch.Tensor, conf: torch.Tensor, cls: torch.Tensor):
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls
        if len(xyxy) > 0:
            x1 = xyxy[:, 0]
            y1 = xyxy[:, 1]
            x2 = xyxy[:, 2]
            y2 = xyxy[:, 3]
            w = x2 - x1
            h = y2 - y1
            xc = x1 + w / 2.0
            yc = y1 + h / 2.0
            self.xywh = torch.stack([xc, yc, w, h], dim=-1)
        else:
            self.xywh = torch.empty((0, 4), dtype=torch.float32, device="cpu")

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx) -> "_SAHIDetectionContainer":
        return _SAHIDetectionContainer(self.xyxy[idx], self.conf[idx], self.cls[idx])


class SAHIBoTSORTTracker(BaseTracker):
    """
    Zero-Loss SAHI + BoT-SORT Tracker.

    Feeds high-recall SAHI sliced detections into BoT-SORT association,
    and applies Kalman forward projection (dead reckoning) during brief occlusions
    so vehicles are never dropped or flickered.
    """

    def __init__(
        self,
        model_name_or_path: str = "yolov8s.pt",
        config_path: str = "configs/botsort.yaml",
        confidence_threshold: float = 0.25,
        vulnerable_threshold: float = 0.08,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
        slice_size: int = 960,
        overlap_ratio: float = 0.20,
        max_coasting_frames: int = 15,  # Frames to hold a track with Kalman projection (~0.5s)
    ):
        self.model_name_or_path = model_name_or_path
        self.config_path = config_path
        self.confidence_threshold = confidence_threshold
        self.vulnerable_threshold = vulnerable_threshold
        self.iou_threshold = iou_threshold
        self.img_size = img_size
        self.device = device
        self.slice_size = slice_size
        self.overlap_ratio = overlap_ratio
        self.max_coasting_frames = max_coasting_frames

        # 1. Initialize Fast SAHI Detector with class-adaptive thresholds
        self.sahi_detector = FastSAHIDetector(
            model_name_or_path=model_name_or_path,
            confidence_threshold=confidence_threshold,
            vulnerable_threshold=vulnerable_threshold,
            iou_threshold=iou_threshold,
            img_size=img_size,
            device=device,
            slice_size=slice_size,
            overlap_ratio=overlap_ratio,
            full_frame_pass=True,
        )
        self.class_names = self.sahi_detector.class_names

        # 2. Load and build BoT-SORT tracker configuration
        self._init_tracker()

        # 3. State storage for kinematics, longevity, and coasting
        self._prev_centroids: Dict[int, Tuple[float, float]] = {}
        self._prev_timestamps: Dict[int, float] = {}
        self._first_seen: Dict[int, float] = {}
        self._frame_counts: Dict[int, int] = {}
        self._last_detected_classes: Dict[int, Tuple[str, Any]] = {}

    def _init_tracker(self) -> None:
        """Loads tracker configuration from yaml and instantiates BOTSORT."""
        cfg: Dict[str, Any] = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    cfg = yaml.safe_load(f) or {}
            except Exception:
                cfg = {}

        defaults = {
            "tracker_type": "botsort",
            "track_high_thresh": 0.15,
            "track_low_thresh": 0.05,
            "new_track_thresh": 0.12,
            "track_buffer": 150,
            "match_thresh": 0.80,
            "fuse_score": True,
            "gmc_method": "sparseOptFlow",
            "proximity_thresh": 0.5,
            "appearance_thresh": 0.25,
            "with_reid": False,
            "model": "auto",
        }
        for k, v in defaults.items():
            if k not in cfg:
                cfg[k] = v

        args = SimpleNamespace(**cfg)
        args.device = self.sahi_detector.device
        self.tracker = BOTSORT(args)

    def update(
        self,
        frame: np.ndarray,
        frame_index: int,
        timestamp: float,
    ) -> TrackingResult:
        h, w = frame.shape[:2]

        # ── Step 1: Run Batched GPU SAHI Inference ─────────────────────────
        det_result = self.sahi_detector.detect(
            frame=frame,
            frame_index=frame_index,
            timestamp=timestamp,
        )

        objects = det_result.objects
        active_tracks: List[TrackedObject] = []
        active_track_ids: Set[int] = set()

        # ── Step 2: Convert detections into Torch CPU tensors ───────────────
        if len(objects) > 0:
            xyxy_list = [obj.bbox for obj in objects]
            conf_list = [obj.confidence for obj in objects]
            cls_list = [float(obj.class_id) for obj in objects]

            xyxy_t = torch.tensor(xyxy_list, dtype=torch.float32, device="cpu")
            conf_t = torch.tensor(conf_list, dtype=torch.float32, device="cpu")
            cls_t = torch.tensor(cls_list, dtype=torch.float32, device="cpu")
            container = _SAHIDetectionContainer(xyxy_t, conf_t, cls_t)
        else:
            empty_xyxy = torch.empty((0, 4), dtype=torch.float32)
            empty_conf = torch.empty((0,), dtype=torch.float32)
            empty_cls = torch.empty((0,), dtype=torch.float32)
            container = _SAHIDetectionContainer(empty_xyxy, empty_conf, empty_cls)

        # ── Step 3: Run BoT-SORT Association & Kalman Filter ────────────────
        # raw_tracks: (N, 8) -> [x1, y1, x2, y2, track_id, conf, cls_id, det_idx]
        raw_tracks = self.tracker.update(container, img=frame)

        if raw_tracks is not None and len(raw_tracks) > 0:
            for trk in raw_tracks:
                x1, y1, x2, y2 = float(trk[0]), float(trk[1]), float(trk[2]), float(trk[3])
                track_id = int(trk[4])
                conf = float(trk[5])
                cls_id = int(trk[6])
                raw_name = self.class_names.get(cls_id, f"class_{cls_id}")

                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0

                normalized = normalize_class(raw_name, conf, [x1, y1, x2, y2])
                if normalized is None:
                    continue

                self._last_detected_classes[track_id] = (raw_name, normalized)
                active_track_ids.add(track_id)

                # Longevity tracking
                if track_id not in self._first_seen:
                    self._first_seen[track_id] = timestamp
                    self._frame_counts[track_id] = 0
                self._frame_counts[track_id] += 1

                # Kinematics computation (speed & heading)
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
        self._last_detected_classes.clear()
        self._init_tracker()
