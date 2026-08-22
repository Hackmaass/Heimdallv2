"""
Ultralytics YOLO Detection Backend
"""

import time
from typing import List, Optional
import numpy as np
from ultralytics import YOLO

from .base import BaseDetector, DetectedObject, DetectionResult


class YOLODetector(BaseDetector):
    """
    Standard Ultralytics YOLO Object Detector (YOLOv8, YOLOv9, YOLOv10, YOLO11).
    """

    def __init__(
        self,
        model_name_or_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
    ):
        super().__init__(
            model_name_or_path=model_name_or_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            img_size=img_size,
            device=device,
        )
        self.model = YOLO(self.model_name_or_path)
        # Move model to target device
        if self.device != "auto":
            try:
                self.model.to(self.device)
            except Exception:
                pass

        self.class_names = self.model.names
        self.prompts: Optional[List[str]] = None

    def set_prompts(self, prompts: List[str]) -> None:
        """Sets target prompt names."""
        self.prompts = prompts

    def detect(self, frame: np.ndarray, frame_index: int = 0, timestamp: float = 0.0) -> DetectionResult:
        """Runs detection on frame."""
        t0 = time.perf_counter()

        results = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            imgsz=self.img_size,
            device=self.device,
            verbose=False,
        )

        inference_ms = (time.perf_counter() - t0) * 1000.0
        detected_objects: List[DetectedObject] = []

        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes
            if boxes is not None:
                for i in range(len(boxes)):
                    box = boxes[i]
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    raw_name = self.class_names.get(cls_id, f"class_{cls_id}")

                    xyxy = box.xyxy[0].tolist()
                    x1, y1, x2, y2 = [float(v) for v in xyxy]
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    detected_objects.append(
                        DetectedObject(
                            class_id=cls_id,
                            raw_class_name=raw_name,
                            confidence=conf,
                            bbox=[x1, y1, x2, y2],
                            centroid=(cx, cy),
                        )
                    )

        return DetectionResult(
            frame_index=frame_index,
            timestamp=timestamp,
            objects=detected_objects,
            inference_time_ms=inference_ms,
            raw_result=results[0] if results else None,
        )
