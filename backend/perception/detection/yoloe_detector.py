"""
YOLOE / YOLO-World Open-Vocabulary Detector Backend
"""

import time
import logging
from typing import List, Optional
import numpy as np
from ultralytics import YOLO

from .base import BaseDetector, DetectedObject, DetectionResult
from .yolo_detector import YOLODetector

logger = logging.getLogger(__name__)


class YOLOEDetector(BaseDetector):
    """
    Open-Vocabulary Promptable Detector (YOLO-World / YOLOE architecture).
    Allows setting custom zero-shot prompts for specialized vehicle and road-user classes.
    Falls back gracefully to standard YOLO if open-vocabulary model weights are not loaded.
    """

    def __init__(
        self,
        model_name_or_path: str = "yolov8s-world.pt",
        confidence_threshold: float = 0.20,
        iou_threshold: float = 0.50,
        img_size: int = 640,
        device: str = "auto",
        prompts: Optional[List[str]] = None,
    ):
        super().__init__(
            model_name_or_path=model_name_or_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            img_size=img_size,
            device=device,
        )
        self.prompts = prompts or [
            "person", "pedestrian", "bicycle", "motorcycle", "scooter",
            "car", "sedan", "SUV", "van", "pickup truck", "truck",
            "heavy truck", "bus", "auto rickshaw", "emergency vehicle"
        ]

        self._fallback_detector: Optional[YOLODetector] = None
        self._is_open_vocab = False

        try:
            self.model = YOLO(self.model_name_or_path)
            if hasattr(self.model, "set_classes"):
                self.model.set_classes(self.prompts)
                self._is_open_vocab = True
                logger.info(f"Initialized Open-Vocabulary detector with {len(self.prompts)} custom prompts")
            else:
                logger.info("Model does not support open-vocabulary set_classes; running standard classes")
        except Exception as e:
            logger.warning(f"Could not load open-vocab model '{self.model_name_or_path}': {e}. Falling back to yolov8n.pt")
            self._fallback_detector = YOLODetector(
                model_name_or_path="yolov8n.pt",
                confidence_threshold=confidence_threshold,
                iou_threshold=iou_threshold,
                img_size=img_size,
                device=device,
            )

    def set_prompts(self, prompts: List[str]) -> None:
        self.prompts = prompts
        if self._is_open_vocab and hasattr(self.model, "set_classes"):
            try:
                self.model.set_classes(prompts)
            except Exception as e:
                logger.warning(f"Failed to update open-vocab classes: {e}")

    def detect(self, frame: np.ndarray, frame_index: int = 0, timestamp: float = 0.0) -> DetectionResult:
        if self._fallback_detector is not None:
            return self._fallback_detector.detect(frame, frame_index, timestamp)

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

                    if self._is_open_vocab and cls_id < len(self.prompts):
                        raw_name = self.prompts[cls_id]
                    else:
                        raw_name = self.model.names.get(cls_id, f"class_{cls_id}")

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
