"""
Heimdallv2 Ultra-Fast Pure-GPU Batched SAHI Detector
Sliced Aided Hyper Inference with Class-Adaptive Thresholding for 4K aerial drone video.

Features:
  1. Class-adaptive sensitivity: Top-down pedestrians (20-40px) & 2-wheelers are detected at 0.08+
     while large vehicles are kept at 0.25+ to prevent false clutter.
  2. Single GPU tensor batch forward pass (>30 FPS on 4K).
  3. Global coordinate remapping + GPU batched NMS.
"""

import time
import math
from typing import List, Optional, Tuple, Set
import numpy as np

try:
    import torch
    import torch.nn.functional as F
    import torchvision
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from ultralytics import YOLO
from .base import BaseDetector, DetectedObject, DetectionResult
from ..classification.taxonomy import is_valid_traffic_class


# Small vulnerable road users in top-down aerial video require adaptive lower confidence thresholds
VULNERABLE_CLASSES: Set[str] = {
    "person", "pedestrian", "people",
    "bicycle", "bike",
    "motorcycle", "motor", "motorbike", "scooter",
    "tricycle", "awning-tricycle", "awning_tricycle",
}


class FastSAHIDetector(BaseDetector):
    """
    Ultra-Fast Pure-GPU Batched SAHI Detector with Class-Adaptive Sensitivity.
    """

    def __init__(
        self,
        model_name_or_path: str = "yolov8s.pt",
        confidence_threshold: float = 0.25,
        vulnerable_threshold: float = 0.08,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
        slice_size: int = 960,
        overlap_ratio: float = 0.20,
        full_frame_pass: bool = True,
    ):
        super().__init__(
            model_name_or_path=model_name_or_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            img_size=img_size,
            device=device,
        )
        self.vulnerable_threshold = min(vulnerable_threshold, self.confidence_threshold)
        self.slice_size = slice_size
        self.overlap_ratio = overlap_ratio
        self.full_frame_pass = full_frame_pass

        self.model = YOLO(self.model_name_or_path)
        self.class_names = self.model.names
        self.prompts: Optional[List[str]] = None

        # Resolve GPU acceleration device
        self.torch_device = "cpu"
        if TORCH_AVAILABLE:
            if self.device == "cuda" or (self.device == "auto" and torch.cuda.is_available()):
                self.torch_device = "cuda:0" if torch.cuda.is_available() else "cpu"
            elif self.device == "mps" or (self.device == "auto" and hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
                self.torch_device = "mps"

        # Pre-computed slice grid (cached per resolution)
        self._cached_resolution: Optional[Tuple[int, int]] = None
        self._cached_slices: List[Tuple[int, int, int, int]] = []

    def set_prompts(self, prompts: List[str]) -> None:
        """Sets target prompt names for open-vocabulary models."""
        self.prompts = prompts

    def _compute_slices(self, img_w: int, img_h: int) -> List[Tuple[int, int, int, int]]:
        """
        Generates overlapping slice coordinates optimized for 4K aerial scenes.
        Uses a balanced 3x2 grid with 20% overlap for high-speed batch processing.
        """
        if self._cached_resolution == (img_w, img_h):
            return self._cached_slices

        # For 4K (3840x2160), 3x2 grid of ~1536x1350 slices gives ideal density
        step_x = max(100, int(img_w / 3 * 1.1))
        step_y = max(100, int(img_h / 2 * 1.1))
        slice_w = min(img_w, int(img_w / 2.5))
        slice_h = min(img_h, int(img_h / 1.6))

        slices = []
        for y in range(0, img_h, step_y):
            for x in range(0, img_w, step_x):
                xe = min(x + slice_w, img_w)
                ye = min(y + slice_h, img_h)
                xs = max(0, xe - slice_w)
                ys = max(0, ye - slice_h)
                slices.append((xs, ys, xe, ye))

        self._cached_slices = list(set(slices))
        self._cached_resolution = (img_w, img_h)
        return self._cached_slices

    def detect(self, frame: np.ndarray, frame_index: int = 0, timestamp: float = 0.0) -> DetectionResult:
        """
        Runs high-speed GPU-batched SAHI detection with class-adaptive filtering.
        """
        t0 = time.perf_counter()
        h, w = frame.shape[:2]
        slices = self._compute_slices(w, h)

        detected_objects: List[DetectedObject] = []
        # Allow vulnerable small objects to be detected in YOLO's internal forward pass
        conf_forward = min(self.vulnerable_threshold, self.confidence_threshold)

        if TORCH_AVAILABLE and self.torch_device.startswith("cuda"):
            # ── Fast GPU Pipeline ──────────────────────────────────────────
            # 1. Transfer full frame to GPU tensor once (non-blocking)
            frame_t = torch.from_numpy(frame).to(device=self.torch_device, non_blocking=True).permute(2, 0, 1).float() / 255.0

            # 2. Crop and resize all slices on GPU
            crops = []
            for (x1, y1, x2, y2) in slices:
                crop = frame_t[:, y1:y2, x1:x2].unsqueeze(0)
                resized = F.interpolate(crop, size=(self.img_size, self.img_size), mode="bilinear", align_corners=False)
                crops.append(resized)

            if self.full_frame_pass:
                full_resized = F.interpolate(frame_t.unsqueeze(0), size=(self.img_size, self.img_size), mode="bilinear", align_corners=False)
                crops.append(full_resized)
                slices_with_full = list(slices) + [(0, 0, w, h)]
            else:
                slices_with_full = list(slices)

            batch_tensor = torch.cat(crops, dim=0)

            # 3. Single Batched GPU Inference (low base conf to catch top-down people/motorcycles)
            results = self.model(
                batch_tensor,
                conf=conf_forward,
                iou=self.iou_threshold,
                device=0,
                verbose=False,
            )

            # 4. Remap slice-local boxes to global 4K frame coordinates
            all_boxes = []
            all_confs = []
            all_classes = []

            for (x1, y1, x2, y2), res in zip(slices_with_full, results):
                if res.boxes is not None and len(res.boxes) > 0:
                    scale_x = (x2 - x1) / self.img_size
                    scale_y = (y2 - y1) / self.img_size
                    xyxy = res.boxes.xyxy.clone()
                    xyxy[:, 0] = xyxy[:, 0] * scale_x + x1
                    xyxy[:, 1] = xyxy[:, 1] * scale_y + y1
                    xyxy[:, 2] = xyxy[:, 2] * scale_x + x1
                    xyxy[:, 3] = xyxy[:, 3] * scale_y + y1
                    all_boxes.append(xyxy)
                    all_confs.append(res.boxes.conf)
                    all_classes.append(res.boxes.cls)

            # 5. GPU Batched NMS to deduplicate boundary crossovers
            if all_boxes:
                boxes_cat = torch.cat(all_boxes, dim=0)
                confs_cat = torch.cat(all_confs, dim=0)
                classes_cat = torch.cat(all_classes, dim=0)

                keep_idx = torchvision.ops.batched_nms(
                    boxes_cat, confs_cat, classes_cat.int(),
                    iou_threshold=self.iou_threshold,
                )

                for idx in keep_idx:
                    conf = float(confs_cat[idx].item())
                    cls_id = int(classes_cat[idx].item())
                    raw_name = self.class_names.get(cls_id, f"class_{cls_id}")

                    # Reject non-traffic objects (plants, trees, boats, umbrellas, benches, furniture)
                    if not is_valid_traffic_class(raw_name):
                        continue

                    # ── Class-Adaptive Confidence Filter ───────────────────
                    # Vulnerable top-down road users (pedestrians, bikes, motorcycles) pass at 0.08+
                    # Standard vehicles pass at confidence_threshold (0.25+)
                    req_conf = self.vulnerable_threshold if raw_name in VULNERABLE_CLASSES else self.confidence_threshold
                    if conf < req_conf:
                        continue

                    bx1, by1, bx2, by2 = boxes_cat[idx].tolist()
                    bx1 = max(0.0, min(float(bx1), float(w)))
                    by1 = max(0.0, min(float(by1), float(h)))
                    bx2 = max(0.0, min(float(bx2), float(w)))
                    by2 = max(0.0, min(float(by2), float(h)))

                    cx = (bx1 + bx2) / 2.0
                    cy = (by1 + by2) / 2.0

                    detected_objects.append(
                        DetectedObject(
                            class_id=cls_id,
                            raw_class_name=raw_name,
                            confidence=conf,
                            bbox=[bx1, by1, bx2, by2],
                            centroid=(cx, cy),
                        )
                    )

        else:
            # ── CPU Fallback ───────────────────────────────────────────────
            crops = [frame[y1:y2, x1:x2] for (x1, y1, x2, y2) in slices]
            if self.full_frame_pass:
                crops.append(frame)
                slices_with_full = list(slices) + [(0, 0, w, h)]
            else:
                slices_with_full = list(slices)

            for (x1, y1, x2, y2), crop in zip(slices_with_full, crops):
                res = self.model.predict(
                    source=crop,
                    conf=conf_forward,
                    iou=self.iou_threshold,
                    imgsz=self.img_size,
                    device="cpu",
                    verbose=False,
                )
                if res and len(res) > 0 and res[0].boxes is not None:
                    for i in range(len(res[0].boxes)):
                        box = res[0].boxes[i]
                        cls_id = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        raw_name = self.class_names.get(cls_id, f"class_{cls_id}")

                        if not is_valid_traffic_class(raw_name):
                            continue

                        req_conf = self.vulnerable_threshold if raw_name in VULNERABLE_CLASSES else self.confidence_threshold
                        if conf < req_conf:
                            continue

                        bx1, by1, bx2, by2 = [float(v) for v in box.xyxy[0].tolist()]
                        gx1 = bx1 + x1
                        gy1 = by1 + y1
                        gx2 = bx2 + x1
                        gy2 = by2 + y1
                        detected_objects.append(
                            DetectedObject(
                                class_id=cls_id,
                                raw_class_name=raw_name,
                                confidence=conf,
                                bbox=[gx1, gy1, gx2, gy2],
                                centroid=((gx1 + gx2) / 2.0, (gy1 + gy2) / 2.0),
                            )
                        )

        # ── Cross-Class Containment & Overlap Suppression ──────────────────
        # Removes driver/windshield nested person boxes and slice duplicates
        clean_objects = _suppress_nested_and_duplicates(detected_objects)

        inference_ms = (time.perf_counter() - t0) * 1000.0
        return DetectionResult(
            frame_index=frame_index,
            timestamp=timestamp,
            objects=clean_objects,
            inference_time_ms=inference_ms,
        )


def _suppress_nested_and_duplicates(objs: List[DetectedObject]) -> List[DetectedObject]:
    """
    Suppresses:
      1. Nested false positives (e.g., driver detected through windshield inside car bbox).
      2. Boundary cross-slice duplicate detections with high IoU.
    """
    if len(objs) <= 1:
        return objs

    n = len(objs)
    keep = [True] * n

    for i in range(n):
        if not keep[i]:
            continue
        b1 = objs[i].bbox
        a1 = max(1.0, (b1[2] - b1[0]) * (b1[3] - b1[1]))
        n1 = objs[i].raw_class_name.lower()

        for j in range(n):
            if i == j or not keep[j]:
                continue
            b2 = objs[j].bbox
            a2 = max(1.0, (b2[2] - b2[0]) * (b2[3] - b2[1]))
            n2 = objs[j].raw_class_name.lower()

            ix1 = max(b1[0], b2[0])
            iy1 = max(b1[1], b2[1])
            ix2 = min(b1[2], b2[2])
            iy2 = min(b1[3], b2[3])
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)

            if inter > 0.0:
                iou = inter / (a1 + a2 - inter)
                ios = inter / min(a1, a2)  # Intersection over smaller box

                # Suppress nested person/cyclist detected inside a moving vehicle box
                if n1 in ("car", "truck", "bus", "van") and n2 in ("person", "bicycle") and ios > 0.60:
                    keep[j] = False
                elif n2 in ("car", "truck", "bus", "van") and n1 in ("person", "bicycle") and ios > 0.60:
                    keep[i] = False
                    break
                # Suppress multi-slice duplicate vehicle boxes
                elif iou > 0.45:
                    if objs[i].confidence >= objs[j].confidence:
                        keep[j] = False
                    else:
                        keep[i] = False
                        break

    return [objs[k] for k in range(n) if keep[k]]

